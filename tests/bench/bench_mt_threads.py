"""对比 ct2 本地翻译在不同 intra_threads 下的实测耗时（当前机器真实负载下）。"""
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from offline_translate.engines import LocalCT2  # noqa: E402

TEXTS = [
    "THE WE",
    "THE WEATHER IS VERY GOOD",
    "THE WEATHER IS VERY GOOD TO THE END WE ARE GOING TO THE PARK",
]

for n in (1, 2, 4):
    eng = LocalCT2(threads=n)
    eng.warm()
    for t in TEXTS:                      # 预热该路径，排除首次分配
        eng.translate(t, "en", "zh")
    ms = []
    for _ in range(5):
        for t in TEXTS:
            t0 = time.monotonic()
            eng.translate(t, "en", "zh")
            ms.append((time.monotonic() - t0) * 1000)
    print(f"threads={n} n={len(ms)} min={min(ms):.0f} p50={statistics.median(ms):.0f} "
          f"max={max(ms):.0f} avg={statistics.mean(ms):.0f}ms", flush=True)
