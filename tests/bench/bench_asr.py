import subprocess
import time

import imageio_ffmpeg
import numpy as np
from faster_whisper import WhisperModel

FF = imageio_ffmpeg.get_ffmpeg_exe()
pcm = subprocess.run(
    [FF, "-v", "error", "-i", "static_hls/test.mp4", "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
    capture_output=True).stdout
audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

for size in ("small", "base", "tiny"):
    t0 = time.time()
    m = WhisperModel(size, device="cpu", compute_type="int8")
    t_load = time.time() - t0
    costs = []
    for start in (0, 2, 4, 6):
        seg = audio[start * 16000:(start + 3) * 16000]
        t = time.time()
        segs, _ = m.transcribe(seg, vad_filter=True, vad_parameters={"min_silence_duration_ms": 300},
                               beam_size=1, best_of=1)
        text = " ".join(s.text.strip() for s in segs).strip()
        costs.append((round(time.time() - t, 2), text))
    print(f"{size}: load={t_load:.1f}s " + " | ".join(f"{c}s {t[:40]}" for c, t in costs), flush=True)
