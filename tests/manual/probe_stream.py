import os, sys, time, wave
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "server"))
import numpy as np
import sherpa_onnx
from streaming_asr import model_files

paths = model_files(sys.argv[1] if len(sys.argv) > 1 else "zh")
t0 = time.monotonic()
rec = sherpa_onnx.OnlineRecognizer.from_transducer(
    tokens=paths["tokens"], encoder=paths["encoder"], decoder=paths["decoder"],
    joiner=paths["joiner"], num_threads=4, sample_rate=16000, feature_dim=80,
    decoding_method="greedy_search", enable_endpoint_detection=True,
    rule1_min_trailing_silence=1.0, rule2_min_trailing_silence=0.4,
    rule3_min_utterance_length=12.0)
print("load_ms", int((time.monotonic()-t0)*1000), "result_type", type(rec.get_result(rec.create_stream())))

w = wave.open(os.path.join(ROOT, "tests", "fixtures", "tts16.wav"), "rb")
pcm = w.readframes(w.getnframes()); w.close()
s = rec.create_stream()
step = int(16000*2*0.256)
for i in range(0, len(pcm), step):
    chunk = pcm[i:i+step]
    a = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)/32768.0
    t = time.monotonic()
    s.accept_waveform(16000, a)
    while rec.is_ready(s):
        rec.decode_stream(s)
    txt = rec.get_result(s)
    ep = rec.is_endpoint(s)
    print(f"chunk {i//step} dec_ms={(time.monotonic()-t)*1000:.0f} ep={ep} text={txt!r}", flush=True)
    if ep:
        rec.reset(s)
