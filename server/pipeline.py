# 实时翻译模块 · 流式字幕管道
# ffmpeg 拉流取音频 → 5s 窗口分片（0.5s 重叠）→ faster-whisper ASR → 翻译 → 回调
# 设计目标：ASR 单线程队列不积压即延迟可控（实测 small-int8 CPU 处理 5s 音频约 1-2s）

import queue
import subprocess
import threading

import numpy as np

from ffmpegbin import get_ffmpeg

SAMPLE_RATE = 16000
BYTES_PER_SEC = SAMPLE_RATE * 2          # s16le 单声道
WINDOW_SEC = 5.0                          # ASR 窗口
OVERLAP_SEC = 0.5                         # 窗口重叠（防切句）
WINDOW_BYTES = int(WINDOW_SEC * BYTES_PER_SEC)
STEP_BYTES = int((WINDOW_SEC - OVERLAP_SEC) * BYTES_PER_SEC)


class StreamPipeline:
    def __init__(self, url: str, on_subtitle, model_size: str = "small"):
        self.url = url
        self.on_subtitle = on_subtitle
        self.model_size = model_size
        self._stop = threading.Event()
        self._proc = None
        self._model = None
        self._asr_q: queue.Queue = queue.Queue(maxsize=4)  # 积压上限：满了丢最旧，保实时性
        self._last_text = ""
        self._threads: list[threading.Thread] = []

    # ---------- 模型 ----------
    def _load_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    # ---------- ffmpeg 拉流 ----------
    def _start_ffmpeg(self):
        cmd = [get_ffmpeg(), "-hide_banner", "-loglevel", "error"]
        if self.url.lower().startswith(("http://", "https://")):
            # reconnect 系 HTTP 协议专用；本地文件/RTMP 加了会直接报错退出
            cmd += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"]
        cmd += ["-i", self.url,
                "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def _reader(self):
        """读 PCM 流，按窗口推入 ASR 队列"""
        buf = bytearray()
        try:
            while not self._stop.is_set():
                chunk = self._proc.stdout.read(8192)
                if not chunk:
                    break
                buf.extend(chunk)
                while len(buf) >= WINDOW_BYTES:
                    window = bytes(buf[:WINDOW_BYTES])
                    del buf[:STEP_BYTES]
                    try:
                        self._asr_q.put_nowait(window)
                    except queue.Full:
                        try:
                            self._asr_q.get_nowait()  # 丢最旧
                        except queue.Empty:
                            pass
                        self._asr_q.put_nowait(window)
        finally:
            self._asr_q.put(None)  # 收尾信号

    # ---------- ASR + 翻译 ----------
    def _asr_worker(self):
        model = self._load_model()
        from translator import Translator
        tr = Translator()
        while True:
            window = self._asr_q.get()
            if window is None or self._stop.is_set():
                break
            audio = np.frombuffer(window, dtype=np.int16).astype(np.float32) / 32768.0
            try:
                segs, info = model.transcribe(
                    audio, vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 400},
                    beam_size=1, best_of=1  # 实时优先：关束搜索
                )
                text = " ".join(s.text.strip() for s in segs).strip()
            except Exception:
                import traceback; traceback.print_exc()
                continue
            if not text or text == self._last_text:
                continue
            self._last_text = text
            try:
                result = tr.translate(text)
                self.on_subtitle(result)
            except Exception:
                import traceback; traceback.print_exc()

    # ---------- 生命周期 ----------
    def start(self):
        self._load_model()  # 预加载，避免第一句高延迟
        self._start_ffmpeg()
        for target in (self._reader, self._asr_worker):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self):
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
        try:
            self._asr_q.put_nowait(None)
        except queue.Full:
            pass
