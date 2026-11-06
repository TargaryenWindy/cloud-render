"""Read host counters outside the render scheduler and HTTP request threads."""
import csv
import ctypes
import json
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
        rows = command(['nvidia-smi', '--query-gpu=name,utilization.gpu,memory.used,memory.total',
                        '--format=csv,noheader,nounits'])
        for row in csv.reader(rows.splitlines(), skipinitialspace=True):
            if len(row) == 4:
                cards.append(dict(name=row[0], load=number(row[1]), used=number(row[2], 2**20), total=number(row[3], 2**20)))
    if os.name != 'nt':
        for device in Path('/sys/class/drm').glob('card[0-9]*/device'):
            if not (device/'gpu_busy_percent').is_file():
                continue
            def read(name):
                path = device/name
                return number(path.read_text()) if path.is_file() else None
            cards.append(dict(name=device.parent.name, load=read('gpu_busy_percent'),
                              used=read('mem_info_vram_used'), total=read('mem_info_vram_total')))
    elif not cards:
        # WDDM exposes memory and individual engine counters keyed by adapter LUID.
        script = """
        $engines=Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine
        $cards=foreach($m in Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory){
          $groups=$engines | Where-Object {$_.Name.Contains($m.Name+'_eng_')} | Group-Object {$_.Name.Substring($_.Name.IndexOf('_eng_'))}
          $loads=foreach($g in $groups){($g.Group | Measure-Object UtilizationPercentage -Sum).Sum}
          [PSCustomObject]@{name=$m.Name;used=$m.DedicatedUsage;load=($loads | Measure-Object -Maximum).Maximum}
        }
        ConvertTo-Json -InputObject @($cards) -Compress
        """
        for index, card in enumerate(json.loads(command(['powershell.exe','-NoProfile','-NonInteractive','-Command',script]) or '[]')):
            cards.append(dict(name=f'GPU {index+1}', load=number(card['load']), used=number(card['used']), total=None))
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
