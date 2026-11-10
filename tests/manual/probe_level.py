# 素材电平检查：每秒 RMS / 峰值，判断素材是否近乎静音
import os
import subprocess

import imageio_ffmpeg
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = os.path.join(ROOT, "tests", "fixtures")
ff = imageio_ffmpeg.get_ffmpeg_exe()

for n in ["tts_ja.wav", "tts_ko.wav", "tts.wav", "speech_ja.mp3", "speech.wav"]:
    p = os.path.join(TMP, n)
    if not os.path.exists(p):
        print(n, "MISSING")
        continue
    out = subprocess.run([ff, "-v", "error", "-i", p, "-f", "s16le",
                          "-ac", "1", "-ar", "16000", "-"], capture_output=True)
    a = np.frombuffer(out.stdout, dtype=np.int16).astype(np.float32)
    if not len(a):
        print(n, "empty", out.stderr.decode("utf-8", "replace")[:200])
        continue
    sec = []
    for i in range(0, len(a), 16000):
        c = a[i:i + 16000]
        sec.append(str(int(np.sqrt(np.mean(c ** 2)))))
    print(f"{n}  {len(a) / 16000:.2f}s  peak={int(np.abs(a).max())}  "
          f"rms={int(np.sqrt(np.mean(a ** 2)))}  per-sec={' '.join(sec[:12])}")
