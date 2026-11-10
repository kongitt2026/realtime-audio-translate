"""offline_translate —— 中日韩英文本翻译（Google 免费端点优先，Argos 离线兜底）。

最小用法：
    from offline_translate import translate
    translate("今日は良い天気です。")          # {'translated': '今天天气很好。', ...}

自定义引擎：
    from offline_translate import Translator, Engine
    class MyEngine(Engine):
        name = "mine"
        def translate(self, text, src, target): return "..."
    Translator(engines=[MyEngine()]).translate("...")
"""
from __future__ import annotations

from .core import Translator
from .engines import (
    ArgosOffline,
    Engine,
    EngineChain,
    EngineError,
    GoogleChrome,
    GoogleGTX,
)
from .lang import detect_lang, normalize_target

__version__ = "1.0.0"

_default: Translator | None = None


def translate(text: str, target: str = "zh-CN") -> dict:
    """模块级快捷函数（复用单例，带缓存）。"""
    global _default
    if _default is None:
        _default = Translator(target=target)
    return _default.translate(text, target)


__all__ = [
    "Translator", "translate", "detect_lang", "normalize_target",
    "Engine", "EngineChain", "EngineError",
    "GoogleGTX", "GoogleChrome", "ArgosOffline",
    "__version__",
]
