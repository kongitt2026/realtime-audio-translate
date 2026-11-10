# 翻译引擎：统一接口 + 四个内置实现（Google gtx / Google clients5 / 本地 CT2 / Argos 离线）
# 自定义引擎只需实现 name / available(src, target) / translate(text, src, target)。
from __future__ import annotations

import os
import re
import threading
import time
import unicodedata

import httpx

GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
# 备选端点：gtx 被限流（429）时使用；返回形如 ["译文"]
CHROME_URL = "https://clients5.google.com/translate_a/t"

DEFAULT_TIMEOUT = 3.0
# 引擎连续失败多少次后进入冷却（跳过），避免每次请求都白等超时
COOLDOWN_AFTER_FAILS = int(os.environ.get("XLATE_COOLDOWN_FAILS", "2"))
COOLDOWN_SECONDS = float(os.environ.get("XLATE_COOLDOWN_SECONDS", "300"))


class EngineError(RuntimeError):
    """引擎不可用或返回空结果，由调用方换下一个引擎。"""


class DegenerateError(EngineError):
    """译文退化为乱码（'⁇' / 一串 '*'）。不换引擎——同一批模型换 Argos 只会更慢且仍然错。"""


class Engine:
    """引擎基类。子类至少覆盖 name 与 translate。"""

    name = "base"

    def available(self, src: str, target: str) -> bool:
        return True

    def translate(self, text: str, src: str, target: str) -> str:
        raise NotImplementedError


class GoogleGTX(Engine):
    """Google gtx 免费端点（默认首选，零配置零费用；高频调用会 429）。"""

    name = "google"

    def __init__(self, timeout: float = DEFAULT_TIMEOUT, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=timeout)
        self._own_client = client is None

    def translate(self, text: str, src: str, target: str) -> str:
        resp = self._client.get(GOOGLE_URL, params={
            "client": "gtx", "sl": src, "tl": target, "dt": "t", "q": text,
        })
        resp.raise_for_status()
        data = resp.json()
        out = "".join(seg[0] for seg in (data[0] or []) if seg and seg[0])
        if not out:
            raise EngineError("empty google result")
        return out

    def close(self):
        if self._own_client:
            self._client.close()


class GoogleChrome(Engine):
    """Google clients5 端点（gtx 被限流时的备用，实测中英日韩均可）。"""

    name = "google_chrome"

    def __init__(self, timeout: float = DEFAULT_TIMEOUT, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=timeout)
        self._own_client = client is None

    def translate(self, text: str, src: str, target: str) -> str:
        resp = self._client.get(CHROME_URL, params={
            "client": "dict-chrome-ex", "sl": src, "tl": target, "q": text,
        })
        resp.raise_for_status()
        data = resp.json()

        def flat(x):
            if isinstance(x, str):
                return [x]
            if isinstance(x, list):
                return [s for i in x for s in flat(i)]
            return []

        out = "".join(flat(data)).strip()
        if not out:
            raise EngineError("empty chrome result")
        return out

    def close(self):
        if self._own_client:
            self._client.close()


def is_degenerate(text: str) -> bool:
    """识别退化解（三层判定，任一命中即判退化）。

    ① 特殊字符占比 ≥20%：Opus-MT 对过短/不完整片段会直接吐 '⁇'(U+2047)。
       实测：'これから声'、'ありがとう' 的 ja→en 输出只有 '⁇'，再经 en→zh
       第二跳就被翻成一串 '* ? *'，最终在字幕上显示为乱码星号。
    ② 重复循环：CT2 在低信息量输入上会陷入短语重复（2026-11-10 ko 实测
       「活佛」×200+、单条 mt_ms=6324），① 拦不住。
    ③ 纯标点输出：整条不含任何字母/数字/文字（实测 ". . ."），不可读。
    这种结果比「不翻译」更糟——调用方拿不到可用译文，宁可按失败处理，
    让字幕回退显示原文（日文假名本身是可读的）。
    """
    core = [ch for ch in text if not ch.isspace()]
    if not core:
        return True
    # ⓪ '⁇'(U+2047) 出现 ≥1 个即退化：正常译文绝不会含此生僻符号；
    #    占比判定拦不住「临 ⁇ 县和 ⁇ 冈县」这种少量混入可读文本的形态
    #    （2026-11-10 NHK 实测，⁇ 由 ja→en 中间跳带入中文，占比仅 ≈11%）。
    if "⁇" in text:
        return True
    junk = sum(1 for ch in core if ch in "⁇?？*＊")
    if junk / len(core) >= 0.2:
        return True
    # ② 同一子串（2-16 字符）连续重复 ≥4 次：「活佛活佛活佛活佛…」形态
    for n in (2, 3, 4, 6, 8, 12, 16):
        if len(core) >= n * 4 and re.search(r"(.{%d})\1{3,}" % n, text):
            return True
    # ③ 纯标点/符号：整条译文没有任何字母(L*)/数字(N*)，等于没说
    if not any(unicodedata.category(ch)[0] in ("L", "N") for ch in core):
        return True
    return False


class LocalCT2(Engine):
    """本地 CTranslate2 翻译（直接复用 Argos 包里的 ct2 模型 + sentencepiece）。

    与 ArgosOffline 用的是同一批模型文件，但**跳过 Argos 的 stanza 分词前置**，
    短句实测 30-100ms（Argos 封装约 800-1000ms），是「≤1 秒字幕」的关键。
    路由：en→zh 直连；ja/ko 走 ja→en→zh 两跳（各约 50ms）。
    """

    name = "local_ct2"

    def __init__(self, packages_dir: str | None = None, threads: int | None = None):
        self._dir = packages_dir or os.environ.get("ARGOS_PACKAGE_DIR") or os.path.join(
            os.path.expanduser("~"), ".local", "share", "argos-translate", "packages")
        # 实测（4 核 8 线程机器，后台负载 80%+）：intra_threads=1/2/4 的平均耗时
        # 130/89/205ms——4 线程与流式 ASR 抢核反而最慢，故默认 2。
        self._threads = int(threads or os.environ.get("XLATE_CT2_THREADS", "2"))
        self._models: dict[tuple[str, str], tuple] = {}
        self._lock = threading.RLock()
        self._pairs: dict[tuple[str, str], str] = self._discover()

    def _discover(self) -> dict[tuple[str, str], str]:
        """扫描包目录，返回 {(src, tgt): 包路径}。兼容 translate-en_zh-1_9 / ja_en 两种命名。"""
        pairs: dict[tuple[str, str], str] = {}
        try:
            names = os.listdir(self._dir)
        except OSError:
            return pairs
        for n in names:
            base = n[len("translate-"):] if n.startswith("translate-") else n
            base = base.split("-")[0]                     # en_zh-1_9 → en_zh
            parts = base.split("_")
            if len(parts) != 2 or not all(len(p) == 2 for p in parts):
                continue
            path = os.path.join(self._dir, n)
            if not (os.path.isdir(os.path.join(path, "model"))
                    and os.path.exists(os.path.join(path, "sentencepiece.model"))):
                continue
            pairs[(parts[0], parts[1])] = path
        return pairs

    @property
    def langs(self) -> set[str]:
        """可直接或两跳到中文的源语种。"""
        out = {src for (src, tgt) in self._pairs if tgt == "zh"}
        if ("en", "zh") in self._pairs:
            out |= {src for (src, tgt) in self._pairs if tgt == "en"}
        return out

    def available(self, src: str, target: str) -> bool:
        if target.split("-")[0].lower() != "zh":
            return False
        return src in self.langs

    def _load(self, src: str, tgt: str):
        key = (src, tgt)
        with self._lock:
            got = self._models.get(key)
            if got is not None:
                return got
            path = self._pairs.get(key)
            if path is None:
                raise EngineError(f"no local model {src}->{tgt}")
            import ctranslate2
            import sentencepiece as spm
            tr = ctranslate2.Translator(os.path.join(path, "model"), device="cpu",
                                        compute_type="int8", inter_threads=1,
                                        intra_threads=self._threads)
            sp = spm.SentencePieceProcessor(model_file=os.path.join(path, "sentencepiece.model"))
            self._models[key] = (tr, sp)
            return self._models[key]

    def warm(self):
        """预加载全部本地模型（含 ja→en / ko→en 中转段），供启动时调用。

        只暖 en→zh 时，第一条日语字幕要现载 ja_en（113MB，实测 1-2s），
        恰好落在「首条字幕」上；把中转段一起暖掉，首条只付识别+翻译成本。
        """
        for src, tgt in list(self._pairs):
            try:
                self._load(src, tgt)
            except Exception:
                pass
        # 深暖：对每个已载语言对跑一次真实 translate_batch。
        # 只 _load 不够——进程内首次推理还有图初始化/内存页载入冷启动
        # （2026-11-10 实测 ja→zh 首条 partial 翻译 1032ms、之后均值 162ms），
        # 恰好落在「首条字幕」上；逐对 dummy 一次后首条只付正常推理成本。
        for tr, sp in list(self._models.values()):
            try:
                tokens = sp.encode("hello", out_type=str)
                if tokens:
                    with self._lock:
                        tr.translate_batch([tokens], beam_size=1, max_decoding_length=32)
            except Exception:
                pass

    @staticmethod
    def _degenerate(s: str) -> bool:
        return is_degenerate(s)

    def _run(self, text: str, src: str, tgt: str) -> str:
        if src == "en":
            # Argos 的 en→zh 模型是按小写语料训练的；流式 ASR 输出全大写，
            # 直接送进去会被当成专名音译（实测 'THE WEATHER IS VERY GOOD' → '韦瑟是非常好的'，
            # 转小写后 → '天气不错'）。
            text = text.lower()
        tr, sp = self._load(src, tgt)
        tokens = sp.encode(text, out_type=str)
        if not tokens:
            raise EngineError("empty tokens")
        with self._lock:
            out = tr.translate_batch([tokens], beam_size=1, max_decoding_length=256)
        zh = sp.decode(out[0].hypotheses[0]).replace("▁", " ").strip()
        if not zh:
            raise EngineError("empty local result")
        if self._degenerate(zh):
            raise DegenerateError(f"degenerate local result: {zh[:20]!r}")
        return zh

    def translate(self, text: str, src: str, target: str) -> str:
        if ("en", "zh") in self._pairs and (src == "en" or (src, "zh") in self._pairs):
            if (src, "zh") in self._pairs:
                return self._run(text, src, "zh")
        if (src, "en") in self._pairs and ("en", "zh") in self._pairs:
            mid = self._run(text, src, "en")          # ja/ko → en
            return self._run(mid, "en", "zh")          # en → zh
        raise EngineError(f"no route {src}->zh")


class ArgosOffline(Engine):
    """Argos Translate 离线兜底。日/韩经英文中转（ja→en→zh），需装 ja_en/ko_en/en_zh。"""

    name = "argos"

    def __init__(self):
        self._langs: set[str] = set()
        self._ready = False
        self._probe()

    def _probe(self):
        try:
            import argostranslate.translate as at
            langs = {lang.code: lang for lang in at.get_installed_languages()}
            zh = langs.get("zh")
            if zh is not None:
                self._langs = {
                    code for code, lang in langs.items()
                    if code != "zh" and lang.get_translation(zh) is not None
                }
            self._ready = bool(self._langs)
        except Exception:
            self._ready = False
            self._langs = set()

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def langs(self) -> set[str]:
        return set(self._langs)

    def refresh(self):
        """装完新模型后调用（或直接重建实例）。"""
        try:
            import argostranslate.translate as at
            at.get_installed_languages.cache_clear()
        except Exception:
            pass
        self._probe()

    def available(self, src: str, target: str) -> bool:
        return src in self._langs and target.split("-")[0].lower() == "zh"

    def translate(self, text: str, src: str, target: str) -> str:
        import argostranslate.translate as at
        out = at.translate(text, src, "zh")
        if not out:
            raise EngineError("empty argos result")
        return out


class EngineChain:
    """按注册顺序尝试的引擎链，带简单熔断：某引擎连续失败 N 次后冷却 M 秒不再尝试。"""

    def __init__(self, engines: list[Engine] | None = None):
        self.engines: list[Engine] = list(engines) if engines else [
            GoogleGTX(), GoogleChrome(), LocalCT2(), ArgosOffline()
        ]
        self._fails: dict[str, int] = {}
        self._skip_until: dict[str, float] = {}
        self._lock = threading.Lock()

    # ---- 熔断 ----
    def usable(self, engine: Engine) -> bool:
        with self._lock:
            return time.monotonic() >= self._skip_until.get(engine.name, 0.0)

    def report_ok(self, engine: Engine):
        with self._lock:
            self._fails.pop(engine.name, None)
            self._skip_until.pop(engine.name, None)

    def report_fail(self, engine: Engine):
        with self._lock:
            n = self._fails.get(engine.name, 0) + 1
            self._fails[engine.name] = n
            if n >= COOLDOWN_AFTER_FAILS:
                self._skip_until[engine.name] = time.monotonic() + COOLDOWN_SECONDS
                self._fails[engine.name] = 0
                print(f"[translate] {engine.name} 连续失败 {n} 次，冷却 {COOLDOWN_SECONDS:.0f}s",
                      flush=True)

    def state(self) -> dict:
        now = time.monotonic()
        with self._lock:
            return {e.name: max(0, round(self._skip_until.get(e.name, 0.0) - now, 1))
                    for e in self.engines}

    def add(self, engine: Engine, first: bool = False) -> "EngineChain":
        if first:
            self.engines.insert(0, engine)
        else:
            self.engines.append(engine)
        return self

    def remove(self, name: str) -> "EngineChain":
        self.engines = [e for e in self.engines if e.name != name]
        return self

    def names(self) -> list[str]:
        return [e.name for e in self.engines]

    def get(self, name: str) -> Engine | None:
        return next((e for e in self.engines if e.name == name), None)

    def close(self):
        for e in self.engines:
            close = getattr(e, "close", None)
            if callable(close):
                close()
