# 查看韩语流式模型的原始输出，确认 ▁（词边界标记）是否被保留
import sys
import wave

import numpy as np

sys.path.insert(0, "server")
from streaming_asr import SAMPLE_RATE, get_recognizer  # noqa: E402

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join("tests", "fixtures", "tts_ko.wav")
lang = sys.argv[2] if len(sys.argv) > 2 else "ko"
with wave.open(path, "rb") as w:
    pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0

rec = get_recognizer(lang)
stream = rec.create_stream()
step = int(SAMPLE_RATE * 0.256)
for i in range(0, len(pcm), step):
    stream.accept_waveform(SAMPLE_RATE, pcm[i:i + step])
    while rec.is_ready(stream):
        rec.decode_stream(stream)
    txt = rec.get_result(stream)
    if txt:
        print(repr(txt), flush=True)
