# -*- coding: utf-8 -*-
"""探针：把日语语音喂给「中英双语」流式模型，看它到底输出什么（根因取证）。"""
import os
import subprocess
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, ROOT)

from imageio_ffmpeg import get_ffmpeg_exe  # noqa: E402
import numpy as np  # noqa: E402
import streaming_asr  # noqa: E402

SRC = os.path.join(ROOT, "tests", "fixtures", "tts_ja.wav")
DST = os.path.join(ROOT, "tests", "_tmp", "tts_ja_16k.wav")
os.makedirs(os.path.dirname(DST), exist_ok=True)
subprocess.run([get_ffmpeg_exe(), "-y", "-i", SRC, "-ar", "16000", "-ac", "1", DST],
               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

with wave.open(DST, "rb") as w:
    pcm = w.readframes(w.getnframes())
samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
print("音频时长 = %.2fs" % (len(samples) / 16000.0))

rec = streaming_asr.get_recognizer()
stream = rec.create_stream()
texts, i, step = [], 0, 4096
while i < len(samples):
    stream.accept_waveform(16000, samples[i:i + step])
    while rec.is_ready(stream):
        rec.decode_stream(stream)
    t = rec.get_result(stream).strip()
    if t and (not texts or t != texts[-1]):
        texts.append(t)
    i += step
    if rec.is_endpoint(stream):
        rec.reset(stream)
print("流式识别输出（逐块变化）：")
for t in texts:
    print("  ", repr(t))
print("FINAL =", repr(rec.get_result(stream).strip()))
