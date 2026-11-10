# -*- coding: utf-8 -*-
"""is_degenerate 三层判定单测（2026-11-10，配合 engines.py v1.14 改动）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from offline_translate.engines import is_degenerate

cases = [
    ("活佛" * 10, True),              # ② 重复循环（ko 实测形态）
    ("今天天气不错" * 5, True),        # ② 6 字短语连排 5 次也是循环
    (". . .", True),                   # ③ 纯标点
    ("⁇", True),                       # ① 特殊字符
    ("临 ⁇ 县和 ⁇ 冈县,这是很强的摇摆", True),  # ⓪ ⁇ 少量混入（NHK 实测形态，占比 <20%）
    ("* ? * ? * ?", True),             # ① 星号乱码
    ("今天天气不错", False),            # 正常中文
    ("天气很好，我们出去散步吧", False),
    ("今日はとてもよい天気です", False),  # 正常日文
    ("财务报告和已审计财务报表", False),  # 短词幻觉形态：无循环、有实字，不属退化解（另案）
    ("OK", False),                     # 极短正常
    ("？", True),                      # 单问号：junk 占比 100%
]

fails = 0
for text, want in cases:
    got = is_degenerate(text)
    if got != want:
        fails += 1
    print(f"{'OK ' if got == want else 'FAIL'} want={want} got={got} {text[:24]!r}")
print("ALL PASS" if fails == 0 else f"{fails} FAILED")
sys.exit(1 if fails else 0)
