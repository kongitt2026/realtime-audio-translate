# 测量三套流式识别器同时加载的耗时与内存占用（决定启动预热策略）
import ctypes
import sys
import time

sys.path.insert(0, "server")

import streaming_asr as s  # noqa: E402


class PMC(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def ws_mb():
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    fn = ctypes.windll.psapi.GetProcessMemoryInfo
    fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong]
    fn.restype = ctypes.c_int
    ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    fn(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return round(pmc.WorkingSetSize / 1048576)


print(f"baseline_MB={ws_mb()}", flush=True)
for lang in ("zh", "ja", "ko"):
    t = time.monotonic()
    s.get_recognizer(lang)
    print(f"{lang}: load_ms={int((time.monotonic()-t)*1000)} rss_MB={ws_mb()}", flush=True)
