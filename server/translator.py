# 兼容层：真正的实现已抽到项目根 offline_translate 包（可独立安装使用）
# 这里只做转发，保证既有 `from translator import Translator` 不失效，避免两份逻辑漂移。

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from offline_translate import Translator, detect_lang  # noqa: E402,F401

__all__ = ["Translator", "detect_lang"]
