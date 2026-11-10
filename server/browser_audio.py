# 浏览器扩展音频管道
# Chrome tabCapture 抓标签页音频 → 前端下采样为 16kHz PCM16 单声道 → 本模块按窗口切片
# 窗口 2.5s / 步进 1.5s → faster-whisper（默认 tiny，可由环境变量 LIVESUB_MODEL 改）
# → 翻译 → 回推字幕
#
# 为什么默认 tiny：本机 i5-9300H（4C8T，通常还有 Chrome 在跑）实测
#   small 处理 3s 音频 ≈ 9-10s（约 0.3x 实时），base ≈ 3-6s，tiny ≈ 1.4-2s
# 实时字幕只能选 tiny；精度换延迟，需更高精度时设 LIVESUB_MODEL=base/small。

import os
import queue
import threading
import time

import numpy as np

SAMPLE_RATE = 16000
BYTES_PER_SEC = SAMPLE_RATE * 2
WINDOW_SEC = 2.5
STEP_SEC = 1.5
WINDOW_BYTES = int(WINDOW_SEC * BYTES_PER_SEC)
STEP_BYTES = int(STEP_SEC * BYTES_PER_SEC)
MODEL_SIZE = os.environ.get("LIVESUB_MODEL", "tiny")
RMS_GATE = float(os.environ.get("LIVESUB_RMS_GATE", "250"))   # 静音门限，防 tiny 在空白处瞎编

# 语种路由：流式 zipformer 覆盖中/英/日/韩（各一套模型，见 streaming_asr._MODEL_DIRS），
# 其它语种仍走本文件的 whisper 通道
SNIFF_SEC = float(os.environ.get("LIVESUB_SNIFF_SEC", "2.0"))
SNIFF_BYTES = int(SNIFF_SEC * BYTES_PER_SEC)
LANG_MIN_PROB = float(os.environ.get("LIVESUB_LANG_MIN_PROB", "0.5"))

_model = None
_model_lock = threading.Lock()


def get_model(size: str | None = None):
    """进程内单例，供启动预热与管道共用，避免重复加载。"""
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(size or MODEL_SIZE, device="cpu",
                                  compute_type="int8", cpu_threads=6)
        return _model


# 模型推理串行锁：whisper 是进程内单例，而语种嗅探、各连接的窗口识别分属不同线程。
# 不加锁时多个 transcribe 会同时把 6 个 ctranslate2 线程打满（4 核机器直接超订），
# 实测第 3 轮连接后单条延迟劣化到 36.8s（mt 33.7s），表现为「越用越不出字幕」。
_infer_lock = threading.Lock()
# 嗅探优先：语种判定必须尽快拿到推理锁。
# 实测（2026-11-09 四连接顺序回归）：第 4 个连接的嗅探被前面连接仍在排队的
# 窗口识别挤在后面，路由晚于客户端断开 → 该连接 0 字幕。窗口识别属低优先级，
# 见 _sniff_waiting 非 0 时在锁外让路。
_sniff_gate = threading.Lock()
_sniff_waiting = 0


_translator = None
_translator_lock = threading.Lock()


def get_translator():
    """进程内单例翻译器（whisper 通道专用）。

    直接复用流式通道的 final 链（本地 CT2 优先），原因有二：
      1) Translator() 冷启动实测 10.2s，若在 _worker 里现建，首个日/韩字幕会被
         白白推迟十几秒——表现为「切到日语后很久不出字幕」；
      2) 默认链把 Google 排在最前，而本机两个免费端点均不可达，每句都要白等
         2×1.2s 才回落本地，日/韩字幕延迟直接多 2 秒多。
    """
    global _translator
    with _translator_lock:
        if _translator is None:
            try:
                from streaming_asr import build_translators
                _translator = build_translators()[1]     # final 链
            except Exception:
                import traceback
                traceback.print_exc()
                from translator import Translator
                _translator = Translator()
        return _translator


def detect_language(audio: "np.ndarray") -> tuple[str, float]:
    """用 whisper 自带的语种判定跑一小段音频，返回 (lang, probability)。

    比「按页面 lang 猜」可靠：视频语音语种与网站界面语种经常不一致。
    高优先级：登记 _sniff_waiting 后直接抢锁，窗口识别会让路。
    """
    global _sniff_waiting
    model = get_model()
    with _sniff_gate:
        _sniff_waiting += 1
    try:
        with _infer_lock:
            segs, info = model.transcribe(
                audio, language=None, beam_size=1, best_of=1,
                vad_filter=False, without_timestamps=True,
            )
            list(segs)   # 消费生成器，确保 info 已填充
    finally:
        with _sniff_gate:
            _sniff_waiting -= 1
    return (info.language or "").lower(), float(getattr(info, "language_probability", 0.0) or 0.0)


def _acquire_window_infer():
    """低优先级取锁：有嗅探排队时先让路（每次让 50ms，不长时间占 _sniff_gate）。"""
    while True:
        with _sniff_gate:
            if _sniff_waiting == 0:
                break
        time.sleep(0.05)
    _infer_lock.acquire()


class BrowserAudioPipeline:
    """接收浏览器推来的 PCM 分片，产出 {original, translated, lang, latency_ms}。"""

    def __init__(self, on_subtitle, model_size: str | None = None):
        self.on_subtitle = on_subtitle
        self.model_size = model_size or MODEL_SIZE
        self._stop = threading.Event()
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._q: queue.Queue = queue.Queue(maxsize=2)   # 积压上限，满了丢最旧保实时
        self._last_text = ""
        self._thread: threading.Thread | None = None
        self._stats = {"chunks": 0, "finals": 0}

    def stats(self) -> dict:
        return {"backend": "whisper", "model": self.model_size, **self._stats}

    def feed(self, data: bytes):
        """由 WebSocket 线程调用，喂入任意长度的 PCM16 字节。"""
        self._stats["chunks"] += 1
        with self._lock:
            self._buf.extend(data)
            while len(self._buf) >= WINDOW_BYTES:
                window = bytes(self._buf[:WINDOW_BYTES])
                del self._buf[:STEP_BYTES]
                rms = float(np.sqrt(np.mean(np.frombuffer(window, dtype=np.int16).astype(np.float32) ** 2)))
                if rms < RMS_GATE:
                    continue          # 静音段直接丢，省算力也防幻觉
                try:
                    self._q.put_nowait((window, time.monotonic()))
                except queue.Full:
                    try:
                        self._q.get_nowait()
                    except queue.Empty:
                        pass
                    self._q.put_nowait((window, time.monotonic()))

    def _worker(self):
        model = get_model(self.model_size)
        tr = get_translator()
        while not self._stop.is_set():
            try:
                window, t_enq = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            audio = np.frombuffer(window, dtype=np.int16).astype(np.float32) / 32768.0
            if self._stop.is_set():
                break
            _acquire_window_infer()
            try:
                segs, _ = model.transcribe(
                    audio, vad_filter=False, beam_size=1, best_of=1,
                    without_timestamps=True, condition_on_previous_text=False,
                )
                text = " ".join(s.text.strip() for s in segs).strip()
            except Exception:
                import traceback; traceback.print_exc()
                continue
            finally:
                _infer_lock.release()
            if not text or text == self._last_text or text in self._last_text:
                continue
            self._last_text = text
            try:
                result = tr.translate(text)
                result["latency_ms"] = int((time.monotonic() - t_enq) * 1000)
                result["asr"] = "whisper"     # 与流式通道对齐，便于前端/日志区分来源
                self._stats["finals"] += 1
                self.on_subtitle(result)
            except Exception:
                import traceback; traceback.print_exc()

    def start(self):
        get_model(self.model_size)   # 预加载，避免首句高延迟
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()


class LangRoutePipeline:
    """语种路由：先嗅探开头 SNIFF_SEC 秒音频，再选后端。

    为什么需要它（历史根因）：日语曾被送进只覆盖中英的流式模型，被强行解码成
    "CURIKARA KO AND YAKIMAS" 这类拉丁字母乱码 —— 表现为「日文字幕显示不出来」。
    所以 audio 必须先由 whisper 判语种，再按语种挑对应模型：
      zh/en/ja/ko 且置信度 ≥ LANG_MIN_PROB → StreamingAudioPipeline(lang=…)
      其它语种/低置信                     → BrowserAudioPipeline（whisper，慢但覆盖广）

    代价：判定前（约 2s）不出字幕；判定完成后把已缓存的音频整段补喂给后端，不丢内容。
    已知语种（?lang=ja 等显式指定）会跳过嗅探，直接进流式，无这 2s 等待。
    """

    def __init__(self, on_subtitle, lang: str | None = None):
        self.on_subtitle = on_subtitle
        self._hint = (lang or "").strip().lower() or None
        self._inner = None
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.detected: str | None = None
        self.prob = 0.0
        self.backend = "pending"

    # ---- 接口对齐 BrowserAudioPipeline ----
    def feed(self, data: bytes):
        with self._lock:
            inner = self._inner
            if inner is None:
                self._buf.extend(data)
                return
        inner.feed(data)

    def start(self):
        if self._hint:
            self._decide(self._hint, 1.0, reason="显式指定")
            return
        self._thread = threading.Thread(target=self._guard(self._sniff), daemon=True, name="asr-sniff")
        self._thread.start()

    def stop(self):
        self._stop.set()
        inner = self._inner
        if inner is not None:
            inner.stop()

    def stats(self) -> dict:
        inner = self._inner
        base = inner.stats() if hasattr(inner, "stats") else {"backend": self.backend}
        base["route_lang"] = self.detected or self._hint or "pending"
        base["route_prob"] = round(self.prob, 2)
        return base

    @staticmethod
    def _guard(fn):
        def run():
            try:
                fn()
            except Exception:
                import traceback
                print("[asr] 语种嗅探线程异常：", flush=True)
                traceback.print_exc()
        return run

    def _sniff(self):
        """攒够 SNIFF_BYTES 或等到 8s 截止，用现有音频判语种。"""
        deadline = time.monotonic() + 8.0
        while not self._stop.is_set() and time.monotonic() < deadline:
            with self._lock:
                n = len(self._buf)
            if n >= SNIFF_BYTES:
                break
            time.sleep(0.05)
        if self._stop.is_set():
            return
        with self._lock:
            raw = bytes(self._buf[:SNIFF_BYTES]) if self._buf else b""
        lang, prob = "", 0.0
        if len(raw) >= int(0.8 * BYTES_PER_SEC):
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            try:
                lang, prob = detect_language(audio)
            except Exception:
                import traceback
                print("[asr] 语种判定失败，按多语种通道处理：", flush=True)
                traceback.print_exc()
        self._decide(lang, prob, reason="自动嗅探")

    def _decide(self, lang: str, prob: float, reason: str):
        # 嗅探期间客户端可能已经断开（语种判定本身要几秒）。此时若照常创建后端，
        # 新管道拿不到 stop()，会变成永远空转的僵尸线程（实测同一进程里叠了多个
        # idle 计数器，越用越慢），所以这里必须挡住。
        if self._stop.is_set():
            print(f"[asr] 连接已关闭，放弃创建后端（{reason}）", flush=True)
            return
        use_stream = False
        if prob >= LANG_MIN_PROB:
            try:
                from streaming_asr import SUPPORTED_LANGS, model_available
                use_stream = lang in SUPPORTED_LANGS and model_available(lang)
            except Exception:
                use_stream = False
        try:
            if use_stream:
                from streaming_asr import StreamingAudioPipeline
                inner = StreamingAudioPipeline(self.on_subtitle, lang=lang)
            else:
                inner = BrowserAudioPipeline(self.on_subtitle)
        except Exception:
            import traceback
            traceback.print_exc()
            inner = BrowserAudioPipeline(self.on_subtitle)
        inner.start()
        with self._lock:
            buffered = bytes(self._buf)
            self._buf.clear()
            self._inner = inner
        self.detected, self.prob = lang or None, prob
        self.backend = "stream" if use_stream else "whisper"
        print(f"[asr] 语种路由（{reason}）lang={lang or '?'} prob={prob:.2f} "
              f"→ {self.backend}", flush=True)
        if buffered:
            inner.feed(buffered)


def create_pipeline(on_subtitle, lang: str | None = None):
    """选择 ASR 后端。

    LIVESUB_ASR：auto(默认) / stream / whisper
    lang：语种提示（zh/en/ja/ko…），来自 /ws/audio?lang= 或 LIVESUB_LANG；
          不传时用 LangRoutePipeline 自动嗅探（见该类注释）。
    """
    mode = os.environ.get("LIVESUB_ASR", "auto").strip().lower()
    hint = (lang or os.environ.get("LIVESUB_LANG") or "").strip().lower() or None
    if mode == "whisper":
        return BrowserAudioPipeline(on_subtitle)
    if mode == "stream":
        try:
            from streaming_asr import StreamingAudioPipeline, model_available
            want = hint or "zh"
            if model_available(want):
                return StreamingAudioPipeline(on_subtitle, lang=want)
            print(f"[asr] 指定 stream 但 {want} 模型文件缺失，回落 whisper", flush=True)
        except Exception:
            import traceback
            traceback.print_exc()
        return BrowserAudioPipeline(on_subtitle)
    return LangRoutePipeline(on_subtitle, lang=hint)
