# 单元测试：语言识别 / 翻译缓存与降级 / 管道去重
# 运行：.venv\Scripts\python.exe tests\test_units.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from translator import Translator, detect_lang  # noqa: E402

PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name if False else ''}{name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


print("== 语言识别 ==")
cases = [
    ("これは日本語です", "ja"), ("東京へ行きます", "ja"),
    ("안녕하세요", "ko"), ("한국어 자막", "ko"),
    ("Hello world this is English", "en"),
    ("这是中文字幕", "zh"), ("中日混合无假名是纯中文", "zh"),
]
for text, exp in cases:
    check(f"detect({text!r})=={exp}", detect_lang(text) == exp)

print("== 翻译器（联网 Google，失败时允许降级） ==")
tr = Translator()
r = tr.translate("Hello, how are you today?")
check("en 翻译返回结构", "translated" in r and "lang" in r)
check("en lang 判定", r["lang"] == "en")
if r.get("failed"):
    print("  [警告] Google 端点不可达，降级原文（联网环境外属预期）")
else:
    check("en→zh 产出中文", detect_lang(r["translated"]) == "zh")

r2 = tr.translate("这是中文不需要翻译")
check("zh 跳过翻译", r2.get("skipped") is True)

# 缓存命中
r3 = tr.translate("Hello, how are you today?")
check("缓存命中", r3.get("cached") is True or r3.get("failed"))

print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
