# 翻译链路检查：日语→中文（本地 CT2）对整句 / 片段的表现
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "server"))

from translator import Translator  # noqa: E402

CASES = [
    "今日はとても良い天気ですね。",
    "コーヒーとケーキをください。",
    "これから声を出します。",
    "これから声",
    "안녕하세요. 오늘 날씨가 좋네요.",
]

t0 = time.time()
tr = Translator()
print("chain =", tr.chain.names() if hasattr(tr, "chain") else tr, flush=True)
print(f"初始化 {time.time() - t0:.2f}s", flush=True)
for s in CASES:
    t = time.time()
    r = tr.translate(s)
    print(f"{time.time() - t:.2f}s  {s!r} → {r.get('translated')!r} "
          f"[lang={r.get('lang')} engine={r.get('engine')}]", flush=True)
