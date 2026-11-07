"""Windows GPU adapter inventory (DXGI) and system-wide WDDM counters (PDH)."""
import ctypes as c
import re
import time
from uuid import UUID

DWORD = c.c_uint32
HANDLE = c.c_void_p


class AdapterDesc(c.Structure):
    _fields_ = [('description', c.c_wchar * 128), ('vendor', DWORD), ('device', DWORD),
                ('subsystem', DWORD), ('revision', DWORD), ('dedicated', c.c_size_t),
                ('system', c.c_size_t), ('shared', c.c_size_t), ('low', DWORD), ('high', DWORD)]


def method(obj, index, result, *args):
    table = c.cast(obj, c.POINTER(c.POINTER(HANDLE))).contents
    return c.WINFUNCTYPE(result, HANDLE, *args)(table[index])


def adapters():
    # IDXGIFactory::EnumAdapters and IDXGIAdapter::GetDesc from dxgi.h.
    factory = HANDLE()
    iid = c.create_string_buffer(UUID('7b7166ec-21c7-44ae-b21a-c9ae321ae369').bytes_le)
    if c.windll.dxgi.CreateDXGIFactory(c.byref(iid), c.byref(factory)):
        return {}
    inventory = {}
    try:
        enum = method(factory, 7, c.c_long, DWORD, c.POINTER(HANDLE))
        index = 0
        while True:
            adapter = HANDLE()
            if enum(factory, index, c.byref(adapter)):
                break
            index += 1
            try:
                desc = AdapterDesc()
                if method(adapter, 8, c.c_long, c.POINTER(AdapterDesc))(adapter, c.byref(desc)):
                    continue
                if desc.vendor == 0x1414:  # Microsoft software adapter
                    continue
                key = (desc.high, desc.low)
                inventory[key] = dict(name=desc.description, vendor=desc.vendor,
                                      total=int(desc.dedicated) or None, used=None, load=None)
            finally:
                method(adapter, 2, DWORD)(adapter)
    finally:
        method(factory, 2, DWORD)(factory)
    return inventory


class Value(c.Structure):
    _fields_ = [('status', DWORD), ('value', c.c_double)]


class Item(c.Structure):
    _fields_ = [('name', c.c_wchar_p), ('value', Value)]


def values(pdh, counter):
    size, count = DWORD(), DWORD()
    # PDH_FMT_DOUBLE, PDH_MORE_DATA. Instances can change between calls.
    for attempt in range(3):
        buffer = c.create_string_buffer(size.value) if size.value else None
        status = pdh.PdhGetFormattedCounterArrayW(counter, 0x200, c.byref(size), c.byref(count), buffer)
        if status == 0 and buffer is not None:
            items = c.cast(buffer, c.POINTER(Item))
            return [(items[i].name, items[i].value.value) for i in range(count.value)
                    if items[i].value.status in (0, 1)]
        if status & 0xffffffff != 0x800007d2:
            break
    return []


def counters():
    pdh = c.windll.pdh
    query = HANDLE()
    if pdh.PdhOpenQueryW(None, 0, c.byref(query)):
        return [], []
    try:
        handles = []
        for path in (r'\GPU Engine(*)\Utilization Percentage', r'\GPU Adapter Memory(*)\Dedicated Usage'):
            handle = HANDLE()
            status = pdh.PdhAddEnglishCounterW(query, path, 0, c.byref(handle))
            handles.append(None if status else handle)
        if any(handles):
            pdh.PdhCollectQueryData(query)
            time.sleep(.5)
            pdh.PdhCollectQueryData(query)
        return [values(pdh, handle) if handle else [] for handle in handles]
    finally:
        pdh.PdhCloseQuery(query)


def readings(inventory, engines, memory, skip_nvidia=False):
    # Each engine has one counter per process. Task Manager shows the busiest engine.
    busy = {}
    for rows, is_engine in ((engines, True), (memory, False)):
        for name, value in rows:
            match = re.search(r'luid_0x([0-9a-f]+)_0x([0-9a-f]+)_phys_(\d+)', name, re.I)
            if not match:
                continue
            key = tuple(int(n, 16) for n in match.groups()[:2])
            if key not in inventory:
                continue
            card = inventory[key]
            if is_engine:
                engine = re.search(r'_eng_(\d+)', name, re.I)
                if engine:
                    slot = key, match[3], engine[1]
                    busy[slot] = busy.get(slot, 0) + value
                    card['load'] = min(100, max(card['load'] or 0, busy[slot]))
            else:
                card['used'] = (card['used'] or 0) + value
    return [{k: v for k, v in card.items() if k != 'vendor'} for card in inventory.values()
            if not (skip_nvidia and card['vendor'] == 0x10de)]


def sample(skip_nvidia=False):
    inventory = adapters()
    if not any(not skip_nvidia or card['vendor'] != 0x10de for card in inventory.values()):
        return []
    return readings(inventory, *counters(), skip_nvidia=skip_nvidia)
