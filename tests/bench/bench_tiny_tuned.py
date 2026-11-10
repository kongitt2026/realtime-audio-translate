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

m = WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=6)
m.transcribe(audio[:16000], beam_size=1)  # 预热

for win in (2.0, 2.5, 3.0):
    costs = []
    for start in (0, 2, 4, 6):
        seg = audio[int(start * 16000):int((start + win) * 16000)]
        t = time.time()
        segs, _ = m.transcribe(seg, vad_filter=False, beam_size=1, best_of=1,
                               without_timestamps=True, condition_on_previous_text=False)
        text = " ".join(s.text.strip() for s in segs).strip()
        costs.append((round(time.time() - t, 2), text))
    print(f"tiny win={win}s " + " | ".join(f"{c}s {t[:45]}" for c, t in costs), flush=True)
