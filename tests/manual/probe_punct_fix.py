# 片段修复验证：日语句尾标点补齐是否能消除「* * ?」退化解
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from offline_translate.engines import LocalCT2  # noqa: E402

ct2 = LocalCT2()
ct2.warm()
CASES = [
    "これから声",
    "これから声。",
    "今日はとても",
    "今日はとても。",
    "ありがとう",
    "ありがとう。",
    "コーヒーとケーキをください",
    "コーヒーとケーキをください。",
]
for s in CASES:
    try:
        ja_en = ct2._run(s, "ja", "en")
    except Exception as e:
        ja_en = f"<EXC {e}>"
    try:
        zh = ct2._run(s, "ja", "zh")
    except Exception as e:
        zh = f"<EXC {e}>"
    print(f"{s!r}\n   ja→en: {ja_en!r}\n   zh   : {zh!r}", flush=True)
