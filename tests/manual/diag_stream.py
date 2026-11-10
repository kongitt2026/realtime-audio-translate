import os, sys, time, wave
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "server"))
from streaming_asr import StreamingAudioPipeline

rows = []
p = StreamingAudioPipeline(lambda r: rows.append(r))
p.start()
time.sleep(0.5)
print("threads:", [(t.name, t.is_alive()) for t in p._threads], flush=True)
# 直接塞一块真实音频
w = wave.open(os.path.join(ROOT, "tests", "fixtures", "tts16.wav"), "rb")
pcm = w.readframes(w.getnframes()); w.close()
step = int(16000*2*0.256)
for i in range(0, len(pcm), step):
    p.feed(pcm[i:i+step]); time.sleep(0.256)
time.sleep(2)
print("stats:", p.stats(), flush=True)
print("threads:", [(t.name, t.is_alive()) for t in p._threads], flush=True)
print("rows:", len(rows))
for r in rows[:5]: print(r)
p.stop()
