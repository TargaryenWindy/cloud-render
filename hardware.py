"""Read host counters outside the render scheduler and HTTP request threads."""
import csv
import ctypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

snapshot = {}


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, errors='replace', timeout=12,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return result.stdout if result.returncode == 0 else ''


def memory():
    if os.name == 'nt':
        class Status(ctypes.Structure):
            _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32)] + [
                (key, ctypes.c_uint64) for key in ('total', 'available', 'page', 'avail_page', 'virtual', 'avail_virtual', 'extended')]
        status = Status()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return [status.total - status.available, status.total]
    else:
        values = dict(re.findall(r'^(MemTotal|MemAvailable):\s+(\d+)', Path('/proc/meminfo').read_text(), re.M))
        total, available = (int(values[k])*1024 for k in ('MemTotal', 'MemAvailable'))
        return [total-available, total]


def number(value, scale=1):
    try:
        return float(value)*scale
    except (TypeError, ValueError):
        return None


def gpus():
    cards = []
    if shutil.which('nvidia-smi'):
        try:
            rows = command(['nvidia-smi', '--query-gpu=name,utilization.gpu,memory.used,memory.total',
                            '--format=csv,noheader,nounits'])
        except (OSError, subprocess.SubprocessError):
            rows = ''
        for row in csv.reader(rows.splitlines(), skipinitialspace=True):
            if len(row) == 4:
                cards.append(dict(name=row[0], load=number(row[1]), used=number(row[2], 2**20), total=number(row[3], 2**20)))
    if os.name == 'nt':
        import windows_gpu
        try:
            cards.extend(windows_gpu.sample(skip_nvidia=bool(cards)))
        except OSError:
            pass
    else:
        cards.extend(linux_cards(Path('/sys/class/drm')))
    return cards


def linux_cards(root):
    def read(path):
        try:
            return path.read_text().strip()
        except OSError:
            return None

    cards = []
    for directory in sorted(root.glob('card[0-9]*')):
        if not re.fullmatch(r'card[0-9]+', directory.name):
            continue
        device = directory / 'device'
        load = number(read(device / 'gpu_busy_percent'))
        used = number(read(device / 'mem_info_vram_used'))
        total = number(read(device / 'mem_info_vram_total'))
        amd = read(device / 'vendor') == '0x1002'
        if amd or any(v is not None for v in (load, used, total)):
            label = read(device / 'product_name') or ('AMD ' if amd else '') + directory.name
            cards.append(dict(name=label, load=load, used=used, total=total))
    return cards


def monitor(directory):
    global snapshot
    while True:
        usage = {}
        for key, reader in [('ram', memory), ('disk', lambda: list(shutil.disk_usage(directory))), ('gpus', gpus)]:
            try:
                usage[key] = reader()
            except (OSError, ValueError, KeyError, subprocess.SubprocessError):
                usage[key] = None
        snapshot = usage
        time.sleep(3)
