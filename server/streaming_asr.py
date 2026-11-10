# 流式 ASR 管道（sherpa-onnx 流式 zipformer，中/英/日/韩）
#
# 与 browser_audio.py 的区别：
#   browser_audio：2.5s 窗口 + faster-whisper 整段识别，单条实测 5.2-5.7s（CPU）
#   本模块      ：逐块增量解码（每块 128-256ms），解码耗时数十毫秒，配合端点检测
#                 把「说话→字幕」压到 1s 量级
#
# 模型（按语种各一套，缺文件时 model_available(lang) 为 False，调用方回落 whisper）：
#   zh/en → models/sherpa-onnx-streaming-zipformer-small-bilingual-zh-en-2023-02-16
#   ja    → models/sherpa-onnx-streaming-zipformer-ar_en_id_ja_ru_th_vi_zh-2025-02-10
#           （sherpa-onnx 没有日语单语流式模型，官方只有 ar/en/id/ja/ru/th/vi/zh 八语种版）
#   ko    → models/sherpa-onnx-streaming-zipformer-korean-2024-06-16
# 目录可用 LIVESUB_STREAM_MODEL / _JA / _KO 覆盖。

import glob
import os
import queue
import threading
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL_DIR = os.path.join(
    ROOT, "models", "sherpa-onnx-streaming-zipformer-small-bilingual-zh-en-2023-02-16"
)
_MODEL_DIRS = {
    # 中英共用一个小模型（int8 四件套约 50MB）
    "zh": os.environ.get("LIVESUB_STREAM_MODEL", DEFAULT_MODEL_DIR),
    "en": os.environ.get("LIVESUB_STREAM_MODEL", DEFAULT_MODEL_DIR),
    # 日语：八语种 multilingual 模型（含 ja/zh/en，int8 encoder+joiner）
    # 目录名沿用官方发布名（解压即得），别改成简写，否则 model_available 判缺失
    "ja": os.environ.get(
        "LIVESUB_STREAM_MODEL_JA",
        os.path.join(
            ROOT, "models",
            "sherpa-onnx-streaming-zipformer-ar_en_id_ja_ru_th_vi_zh-2025-02-10",
        ),
    ),
    "ko": os.environ.get(
        "LIVESUB_STREAM_MODEL_KO",
        os.path.join(ROOT, "models", "sherpa-onnx-streaming-zipformer-korean-2024-06-16"),
    ),
}
SUPPORTED_LANGS = tuple(dict.fromkeys(_MODEL_DIRS))   # ("zh","en","ja","ko")
SAMPLE_RATE = 16000
NUM_THREADS = int(os.environ.get("LIVESUB_STREAM_THREADS", "2"))   # 与翻译抢核，2 线程足够
PARTIAL_MS = int(os.environ.get("LIVESUB_PARTIAL_MS", "600"))   # 部分结果最短刷新间隔
MIN_PARTIAL_CHARS = int(os.environ.get("LIVESUB_PARTIAL_MIN_CHARS", "3"))
# 端点判定（秒）：停顿多久算一句说完。越小越实时，太大则字幕不出、太小则断句碎
RULE1_SILENCE = float(os.environ.get("LIVESUB_RULE1_SILENCE", "1.0"))
RULE2_SILENCE = float(os.environ.get("LIVESUB_RULE2_SILENCE", "0.4"))
RULE3_LEN = float(os.environ.get("LIVESUB_RULE3_LEN", "12"))

_recognizers: dict[str, object] = {}
_lock = threading.Lock()


def _pick(dirpath: str, stem: str) -> str | None:
    """在模型目录里挑同名前缀的 onnx（优先 int8）。

    三套模型的训练轮次与后缀都不同（epoch-99-avg-1 / epoch-75-avg-11-chunk-16-left-128），
    按前缀取文件比写死文件名更耐受换模型，也避免某个模型只发布 fp32 时被判缺失。
    """
    cands = sorted(glob.glob(os.path.join(dirpath, f"{stem}*.onnx")))
    int8 = [c for c in cands if c.endswith(".int8.onnx")]
    return (int8 or cands or [None])[0]


def model_files(lang: str) -> dict | None:
    """返回某语种的模型四件套路径；缺任意一件返回 None（调用方回落 whisper）。"""
    dirpath = _MODEL_DIRS.get((lang or "").strip().lower())
    if not dirpath or not os.path.isdir(dirpath):
        return None
    paths = {
        "tokens": os.path.join(dirpath, "tokens.txt"),
        "encoder": _pick(dirpath, "encoder"),
        "decoder": _pick(dirpath, "decoder"),
        "joiner": _pick(dirpath, "joiner"),
    }
    return paths if all(paths.values()) and os.path.exists(paths["tokens"]) else None


def model_available(lang: str = "zh") -> bool:
    return model_files(lang) is not None


def _warm_decode(rec, seconds: float = 0.6):
    """拿 0.6s 静音空跑一遍，把 onnxruntime 的计算图/内存池热起来。

    不预热时首个真实音频块实测要 500-800ms（图初始化），后面才降到 100ms 级；
    这段尖峰正好落在第一条字幕上，表现为「切到日语/韩语后第一句特别慢」。
    """
    stream = rec.create_stream()
    chunk = SAMPLE_RATE // 10
    samples = np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)
    for i in range(0, len(samples), chunk):
        stream.accept_waveform(SAMPLE_RATE, samples[i:i + chunk])
        while rec.is_ready(stream):
            rec.decode_stream(stream)


def get_recognizer(lang: str = "zh"):
    """按语种取识别器单例；首次加载 5-20s（含静音空跑预热），由 warm_up()/warm_extra_langs() 预热。"""
    lang = (lang or "zh").strip().lower()
    if lang not in _MODEL_DIRS:
        lang = "zh"
    with _lock:
        rec = _recognizers.get(lang)
        if rec is None:
            import sherpa_onnx

            paths = model_files(lang)
            if paths is None:
                raise RuntimeError(f"流式模型缺失：lang={lang} dir={_MODEL_DIRS.get(lang)}")
            rec = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=paths["tokens"],
                encoder=paths["encoder"],
                decoder=paths["decoder"],
                joiner=paths["joiner"],
                num_threads=NUM_THREADS,
                sample_rate=SAMPLE_RATE,
                feature_dim=80,
                decoding_method="greedy_search",
                enable_endpoint_detection=True,
                rule1_min_trailing_silence=RULE1_SILENCE,
                rule2_min_trailing_silence=RULE2_SILENCE,
                rule3_min_utterance_length=RULE3_LEN,
            )
            try:
                _warm_decode(rec)
            except Exception:
                import traceback
                print(f"[warmup] {lang} 空跑预热失败（不影响功能）：", flush=True)
                traceback.print_exc()
            _recognizers[lang] = rec
        return rec


_local_ct2 = None
_local_lock = threading.Lock()


def _shared_local():
    """进程内唯一的本地翻译引擎（82MB 模型只载一次，多次连接/多个标签页复用）。"""
    global _local_ct2
    with _local_lock:
        if _local_ct2 is None:
            from translator import Translator  # noqa: F401  兼容层：先把项目根加入 sys.path
            from offline_translate.engines import LocalCT2
            _local_ct2 = LocalCT2()
            _local_ct2.warm()
        return _local_ct2


def build_translators():
    """返回 (fast, full)：partial 求快、final 求准。

    final 默认也走本地 CT2：本机实测 Google 两个免费端点全部不可达（gtx 429 /
    clients5 超时），若把 Google 排在前面，每句都要先白等 1.2s×2 才回落，
    「≤1 秒」直接失守。要启用 Google（需先实测该网络能通）设 LIVESUB_MT_GOOGLE=1。
    """
    from translator import Translator

    local = _shared_local()
    if os.environ.get("LIVESUB_MT_GOOGLE", "0") == "1":
        from offline_translate.engines import GoogleChrome, GoogleGTX
        tmo = float(os.environ.get("LIVESUB_MT_TIMEOUT", "1.2"))
        full = Translator(engines=[GoogleGTX(timeout=tmo), GoogleChrome(timeout=tmo), local])
    else:
        full = Translator(engines=[local])
    fast = Translator(engines=[local])
    return fast, full


def warm_up():
    """服务启动时同步预热中英识别器 + 翻译链（最常用语种，首个连接零等待）。"""
    get_recognizer("zh")
    _, full = build_translators()
    return full.chain.names()


def warm_extra_langs(langs=("ja", "ko")):
    """后台补热日/韩识别器。

    不放进 warm_up：三套模型一起加载会拖慢服务就绪；但也不能等首个日语连接时才加载，
    否则切到日语的第一条字幕要吃 1-4s 模型加载（正是本次要解决的延迟）。
    """
    for lang in langs:
        if not model_available(lang):
            print(f"[warmup] 流式 {lang} 模型缺失，该语种回落 whisper", flush=True)
            continue
        try:
            t0 = time.monotonic()
            get_recognizer(lang)
            print(f"[warmup] 流式 {lang} 识别器就绪"
                  f"（{(time.monotonic() - t0) * 1000:.0f}ms）", flush=True)
        except Exception:
            import traceback
            print(f"[warmup] 流式 {lang} 预热失败：", flush=True)
            traceback.print_exc()


class StreamingAudioPipeline:
    """接口与 BrowserAudioPipeline 一致：feed(bytes) / start() / stop()。

    产出字幕字段：original / translated / lang / target / engine / latency_ms
    另附 partial(bool)=是否为中间结果、asr="stream"。

    双线程设计（关键）：
      解码线程：只做 accept_waveform + decode，绝不等翻译（否则翻译一卡，
                解码就停，实测会掉到 0 字幕）。
      翻译线程：final 走「高质量链」（Google 短超时 → 本地 CT2 → Argos）；
                partial 只走本地 CT2（30-100ms），且只保留最新一条（覆盖式），
                保证中间字幕永远追着最新音频走，不排长队。
    """

    def __init__(self, on_subtitle, lang: str = "zh"):
        self.on_subtitle = on_subtitle
        self.lang = (lang or "zh").strip().lower()
        if self.lang not in _MODEL_DIRS:
            self.lang = "zh"
        self._stop = threading.Event()
        self._q: queue.Queue = queue.Queue(maxsize=64)   # 音频块，64 × 256ms ≈ 16s 抗抖动
        self._finals: queue.Queue = queue.Queue(maxsize=8)  # 待翻译的定稿，满了丢最旧
        self._pending = None                              # 最新的未翻译 partial（覆盖式）
        self._pending_lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._last_text = ""
        self._last_partial_t = 0.0
        self._idles = 0
        self._t0: float | None = None
        self._stats = {"chunks": 0, "decode_ms": 0.0, "partials": 0, "finals": 0,
                       "mt_ms": 0.0, "mt_n": 0, "first_subtitle_ms": None}

    # ---- 供外部探测 ----
    def stats(self) -> dict:
        s = dict(self._stats)
        s["chunks"] = int(s["chunks"])
        s["decode_ms"] = round(float(s["decode_ms"]), 1)
        s["mt_avg_ms"] = round(float(s["mt_ms"]) / s["mt_n"], 1) if s["mt_n"] else 0.0
        s["model_lang"] = self.lang
        return s

    def feed(self, data: bytes):
        if self._t0 is None:
            self._t0 = time.monotonic()
        try:
            self._q.put_nowait((data, time.monotonic()))
        except queue.Full:
            try:
                self._q.get_nowait()      # 丢最旧，保实时
            except queue.Empty:
                pass
            try:
                self._q.put_nowait((data, time.monotonic()))
            except queue.Full:
                pass

    # ---- 解码线程 → 翻译线程的交接 ----
    def _push_final(self, text: str, t_audio: float):
        try:
            self._finals.put_nowait((text, t_audio))
        except queue.Full:
            try:
                self._finals.get_nowait()
            except queue.Empty:
                pass
            try:
                self._finals.put_nowait((text, t_audio))
            except queue.Full:
                pass

    def _push_partial(self, text: str, t_audio: float):
        with self._pending_lock:
            self._pending = (text, t_audio)   # 只留最新，旧的直接丢

    def _emit(self, text: str, t_audio: float, tr, final: bool):
        text = text.strip()
        if not text:
            return
        t_mt = time.monotonic()
        try:
            result = tr.translate(text)
        except Exception:
            import traceback
            traceback.print_exc()
            result = {"original": text, "translated": text, "lang": "?", "target": "zh-CN",
                      "engine": "failed"}
        mt_ms = (time.monotonic() - t_mt) * 1000
        self._stats["mt_ms"] += mt_ms
        self._stats["mt_n"] += 1
        latency = int((time.monotonic() - t_audio) * 1000)
        result["latency_ms"] = latency
        result["partial"] = not final
        result["asr"] = "stream"
        if self._stats["first_subtitle_ms"] is None:
            self._stats["first_subtitle_ms"] = latency
        if final:
            self._stats["finals"] += 1
            print(f"[stream] final latency_ms={latency} mt_ms={mt_ms:.0f} "
                  f"engine={result.get('engine')} text={text[:60]!r}", flush=True)
        else:
            self._stats["partials"] += 1
            if os.environ.get("LIVESUB_DEBUG"):
                print(f"[stream] partial latency_ms={latency} mt_ms={mt_ms:.0f} "
                      f"text={text[:60]!r}", flush=True)
        self.on_subtitle(result)

    # ---- 线程 1：解码（绝不阻塞在翻译上）----
    def _text(self, rec, stream) -> str:
        """取当前识别文本。

        韩语必须保留词间空格：get_result() 返回的是去掉词边界的连写文本
        （实测 '오늘은날씨가정말좋습니다.' 送进翻译 → '今取为所取之所取.' 乱码；
        带空格 → '今天天气不错'）。token 级结果里词边界已还原成空格，故韩语走 token 拼接。
        中/英/日的 get_result 已是正确形态，保持原样，避免引入回归。
        """
        if self.lang == "ko":
            try:
                toks = rec.tokens(stream)
            except Exception:
                toks = None
            if toks:
                return "".join(toks).strip()
        return rec.get_result(stream).strip()

    def _decode_worker(self):
        rec = get_recognizer(self.lang)
        stream = rec.create_stream()
        while not self._stop.is_set():
            try:
                data, t_arrive = self._q.get(timeout=0.3)
            except queue.Empty:
                if os.environ.get("LIVESUB_DEBUG"):
                    self._idles += 1
                    print(f"[dbg] idle#{self._idles} chunks={self._stats['chunks']} "
                          f"q={self._q.qsize()} stop={self._stop.is_set()}", flush=True)
                # 音频断供（视频暂停/切走）：把残留话尾收成一句，避免半句卡住
                text = self._text(rec, stream)
                if text:
                    self._push_final(text, time.monotonic())
                rec.reset(stream)          # reset 后 get_result 为空，不会重复推
                self._last_text = ""
                self._last_partial_t = 0.0
                continue

            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            t_dec = time.monotonic()
            try:
                stream.accept_waveform(SAMPLE_RATE, samples)
                while rec.is_ready(stream):
                    rec.decode_stream(stream)
                text = self._text(rec, stream)
                endpoint = rec.is_endpoint(stream)
            except Exception:
                import traceback
                traceback.print_exc()
                rec.reset(stream)
                continue
            dt_ms = (time.monotonic() - t_dec) * 1000
            self._stats["chunks"] += 1
            self._stats["decode_ms"] += dt_ms
            if os.environ.get("LIVESUB_DEBUG"):
                print(f"[dbg] chunk#{self._stats['chunks']} dec={dt_ms:.0f}ms "
                      f"ep={endpoint} text={text[:50]!r}", flush=True)

            if endpoint:
                # 必须用「是否等于上一条 final」判重，不能和 partial 比：
                # 端点触发时的文本通常与最后一次 partial 完全相同，用 _last_text 比会漏掉 final。
                if text:
                    self._push_final(text, t_arrive)
                rec.reset(stream)
                self._last_text = ""
                self._last_partial_t = 0.0
                continue

            # 中间结果：按最短间隔 + 最小增量刷新；翻译线程只取最新一条
            if (text and text != self._last_text
                    and len(text) >= MIN_PARTIAL_CHARS
                    and (time.monotonic() - self._last_partial_t) * 1000 >= PARTIAL_MS):
                self._last_text = text
                self._last_partial_t = time.monotonic()
                self._push_partial(text, t_arrive)
                if os.environ.get("LIVESUB_DEBUG"):
                    print(f"[dbg] push_partial {text[:40]!r}", flush=True)

    # ---- 线程 2：翻译（final 优先，partial 只追最新）----
    def _translate_worker(self, fast, full):
        while not self._stop.is_set():
            try:
                text, t_arrive = self._finals.get(timeout=0.05)
            except queue.Empty:
                text = None
            if text is not None:
                self._emit(text, t_arrive, full, final=True)
                continue
            with self._pending_lock:
                item, self._pending = self._pending, None
            if item is not None:
                if os.environ.get("LIVESUB_DEBUG"):
                    print(f"[dbg] mt take partial {item[0][:40]!r}", flush=True)
                self._emit(item[0], item[1], fast, final=False)

    def start(self):
        get_recognizer()          # 预热，避免首句吃 1-2s 模型加载
        # 翻译链必须在 feed 之前就绪：否则初始化那 1-1.3s 内到达的音频只能排队，
        # 首条字幕会被推后同样时长（实测冷启动可到 9s，表现为「有连接但 0 字幕」）。
        t_build = time.monotonic()
        fast, full = build_translators()
        if os.environ.get("LIVESUB_DEBUG"):
            print(f"[dbg] 翻译链就绪 {full.chain.names()} "
                  f"耗时={(time.monotonic() - t_build) * 1000:.0f}ms", flush=True)
        self._threads = [
            threading.Thread(target=self._guard(self._decode_worker, "asr-decode"),
                             daemon=True, name="asr-decode"),
            threading.Thread(target=self._guard(lambda: self._translate_worker(fast, full), "asr-mt"),
                             daemon=True, name="asr-mt"),
        ]
        for t in self._threads:
            t.start()

    @staticmethod
    def _guard(fn, tag: str):
        """线程体兜底：任何未捕获异常都要打日志，不能静默死掉（否则表现为 0 字幕）。"""
        def run():
            try:
                fn()
            except Exception:
                import traceback
                print(f"[stream] 线程 {tag} 异常退出：", flush=True)
                traceback.print_exc()
        return run

    def stop(self):
        self._stop.set()
