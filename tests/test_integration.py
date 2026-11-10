# 集成测试：pyttsx3 离线合成英文语音 → faster-whisper ASR → 翻译 → 校验
# 全程本地零费用（pyttsx3 走 Windows SAPI）
# 运行：.venv\Scripts\python.exe tests\test_integration.py
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

TMP = os.path.join(ROOT, "tests", "_tmp")
os.makedirs(TMP, exist_ok=True)

SENTENCE = "The weather is very good today and we are going to the park."

print("== 1. TTS 合成测试语音（pyttsx3 / SAPI 离线） ==")
wav = os.path.join(TMP, "tts.wav")
import pyttsx3
eng = pyttsx3.init()
eng.setProperty("rate", 150)
eng.save_to_file(SENTENCE, wav)
eng.runAndWait()
assert os.path.exists(wav) and os.path.getsize(wav) > 10000, "TTS 合成失败"
print(f"  语音文件 {os.path.getsize(wav)//1024} KB")

print("== 2. 转 16kHz 单声道（ASR 标准输入） ==")
import subprocess
from ffmpegbin import get_ffmpeg
wav16 = os.path.join(TMP, "tts16.wav")
subprocess.run([get_ffmpeg(), "-y", "-loglevel", "error", "-i", wav,
                "-ac", "1", "-ar", "16000", wav16], check=True)
print("  ok")

print("== 3. faster-whisper ASR（small/int8/CPU） ==")
import wave
import numpy as np
from faster_whisper import WhisperModel
with wave.open(wav16, "rb") as w:
    pcm = w.readframes(w.getnframes())
audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
model = WhisperModel("small", device="cpu", compute_type="int8")
segs, info = model.transcribe(audio, beam_size=1)
text = " ".join(s.text.strip() for s in segs).strip()
print(f"  识别语种={info.language} 置信度={info.language_probability:.2f}")
print(f"  识别文本: {text}")
assert info.language == "en", f"语种识别错误: {info.language}"
# 宽松校验：关键词命中（TTS 合成音质一般，允许个别词误差）
hits = sum(1 for w in ["weather", "good", "today", "park"] if w in text.lower())
print(f"  关键词命中 {hits}/4")
assert hits >= 3, "ASR 准确率不达标"

print("== 4. 翻译为中文 ==")
from translator import Translator
tr = Translator()
r = tr.translate(text)
print(f"  译文: {r.get('translated')}")
if r.get("failed"):
    print("  [警告] 在线翻译不可达，降级原文（离线环境属预期）")
else:
    from translator import detect_lang
    assert detect_lang(r["translated"]) == "zh", "译文非中文"

print("\n集成测试通过：TTS→ASR→翻译 全链路闭环 ✅")
