# 翻译器门面：语言识别 → 引擎链 → 缓存。无 Web 框架依赖，可嵌入任意 Python 项目。
from __future__ import annotations

import threading

from .engines import DegenerateError, Engine, EngineChain, is_degenerate
from .lang import detect_lang, normalize_target

DEFAULT_CHAIN = ("google", "google_chrome", "local_ct2", "argos")


class Translator:
    """可独立使用的翻译器。

    参数：
        target:    默认目标语种，zh-CN / en / ja ...（Argos 内部只用两位码）
        engines:   自定义引擎列表；None 时用内置链 google → google_chrome → argos
        timeout:   内置 HTTP 引擎超时（秒）
        cache_cap: 进程内缓存条数上限，0 表示关闭缓存

    返回：{"original", "translated", "lang", "engine"}，另有
        skipped=True（中文/无法识别，原样返回）、
        cached=True（命中缓存，无 engine）、
        failed=True + error（全链失败，translated 回退原文）
    """

    def __init__(self, target: str = "zh-CN", engines: list[Engine] | None = None,
                 timeout: float = 3.0, cache_cap: int = 1000):
        self.target = normalize_target(target)
        self.cache: dict[str, str] = {}
        self.cache_cap = max(0, cache_cap)
        self._lock = threading.Lock()
        self.chain = EngineChain(engines if engines is not None else self._default_engines(timeout))

    @staticmethod
    def _default_engines(timeout: float) -> list[Engine]:
        from .engines import ArgosOffline, GoogleChrome, GoogleGTX, LocalCT2
        return [GoogleGTX(timeout=timeout), GoogleChrome(timeout=timeout),
                LocalCT2(), ArgosOffline()]

    # ---------- 对外接口 ----------
    def translate(self, text: str, target: str | None = None) -> dict:
        text = (text or "").strip()
        target = normalize_target(target or self.target)
        if not text:
            return {"original": "", "translated": "", "lang": "other", "target": target, "skipped": True}

        lang = detect_lang(text)
        if lang in ("zh", "other"):
            return {"original": text, "translated": text, "lang": lang, "target": target, "skipped": True}

        # 多行文本按行翻译再拼回：引擎（Google gtx / CT2）会把换行符吞掉，
        # 字幕里的两行台词会粘成一行（实测 J7/K7）。空行原样保留。
        if "\n" in text:
            outs, engine_used, first_err = [], None, None
            degraded = False
            for line in text.split("\n"):
                if not line.strip():
                    outs.append(line)
                    continue
                r = self._translate_line(line.strip(), lang, target)
                outs.append(r["translated"])
                engine_used = engine_used or r.get("engine")
                # 子行失败时 translated 是原文，必须把失败状态带出来，
                # 否则调用方看到的是中英/中韩混排却以为翻译成功了。
                if r.get("failed") and not degraded:
                    degraded = True
                    first_err = r.get("error")
            out = {"original": text, "translated": "\n".join(outs), "lang": lang,
                   "target": target, "engine": engine_used or "multiline"}
            if degraded:
                out.update({"failed": True, "error": first_err})
            return out

        return self._translate_line(text, lang, target)

    def _translate_line(self, text: str, lang: str, target: str) -> dict:
        """单行翻译：缓存 → 引擎链 → 退化判定。translate() 与多行分支共用。"""
        key = f"{lang}::{target}::{text}"
        if self.cache_cap:
            with self._lock:
                hit = self.cache.get(key)
            if hit is not None:
                return {"original": text, "translated": hit, "lang": lang,
                        "target": target, "cached": True}

        last_err = None
        degenerate = False
        for engine in self.chain.engines:
            if not self.chain.usable(engine):      # 熔断冷却中的引擎直接跳过
                continue
            try:
                if not engine.available(lang, target):
                    continue
                out = engine.translate(text, lang, target)
                if is_degenerate(out):
                    # 星号/问号占满的译文会直接显示成乱码，按退化解处理
                    raise DegenerateError(f"degenerate output: {out[:20]!r}")
                self.chain.report_ok(engine)
                if self.cache_cap:
                    with self._lock:
                        self.cache[key] = out
                        if len(self.cache) > self.cache_cap:
                            self.cache.pop(next(iter(self.cache)))
                return {"original": text, "translated": out, "lang": lang,
                        "target": target, "engine": engine.name}
            except DegenerateError as e:
                # 不换引擎：同一批模型换到 Argos 只会更慢（实测 10.6s）且仍是错的，
                # 直接回退原文——日文假名本身可读，比显示 '* ? *' 强得多。
                last_err, degenerate = e, True
                break
            except Exception as e:  # 换下一个引擎
                self.chain.report_fail(engine)
                last_err = e
        return {"original": text, "translated": text, "lang": lang,
                "target": target, "failed": True, "degenerate": degenerate,
                "error": str(last_err)}

    def translate_batch(self, texts: list[str], target: str | None = None) -> list[dict]:
        return [self.translate(t, target) for t in texts]

    def health(self) -> dict:
        argos = self.chain.get("argos")
        langs = sorted(argos.langs) if argos is not None else []
        local = self.chain.get("local_ct2")
        return {
            "chain": self.chain.names(),
            "target": self.target,
            "argos_ready": bool(argos is not None and argos.ready),
            "offline_langs": langs,
            "local_ct2_langs": sorted(local.langs) if local is not None else [],
            "cooldown": self.chain.state(),
            "cache_size": len(self.cache),
        }

    def refresh_offline(self):
        """装完 Argos 模型后调用，无需重启进程。"""
        argos = self.chain.get("argos")
        if argos is not None:
            argos.refresh()

    def close(self):
        self.chain.close()
