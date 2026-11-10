# 日语/韩语 ASR 验证：edge-tts 在线合成（免费、无 Key）→ 16k 单声道 → faster-whisper small/int8 → 字错率统计 → 翻译
# 运行：.venv\Scripts\python.exe tests\test_asr_ja_ko.py
# 说明：本机无 ja/ko SAPI 语音包，故用 edge-tts 合成标准朗读音；合成音比真实口语干净，结果偏乐观
import asyncio
import difflib
import os
import re
import subprocess
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

import numpy as np
from faster_whisper import WhisperModel
from ffmpegbin import get_ffmpeg

TMP = os.path.join(ROOT, "tests", "_tmp")
os.makedirs(TMP, exist_ok=True)

CASES = [
    ("ja", "ja-JP-NanamiNeural", "今日はとても良い天気です。これから公園へ行きます。"),
    ("ko", "ko-KR-SunHiNeural", "오늘은 날씨가 정말 좋습니다. 우리는 공원에 갈 거예요."),
]

# 关键词（ASR 结果里必须出现，用于宽松校验）
KEYWORDS = {
    "ja": ["天気", "公園"],
    "ko": ["날씨", "공원"],
}


def synth(text: str, voice: str, out_mp3: str):
    import edge_tts
    asyncio.run(edge_tts.Communicate(text, voice).save(out_mp3))


def to_pcm16k(src: str, dst: str):
    subprocess.run([get_ffmpeg(), "-y", "-loglevel", "error", "-i", src,
                    "-ac", "1", "-ar", "16000", dst], check=True)


def load_audio(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        pcm = w.readframes(w.getnframes())
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def norm(s: str) -> str:
    """去掉标点与空白，只留文字，便于算字错率"""
    return re.sub(r"[\s。、，．,.!?！？「」『』\"'·…\-]", "", s)


def cer(ref: str, hyp: str) -> float:
    r, h = norm(ref), norm(hyp)
    if not r:
        return 1.0
    sm = difflib.SequenceMatcher(None, r, h)
    same = sum(b.size for b in sm.get_matching_blocks())
    return 1 - same / len(r)


def main():
    model = WhisperModel("small", device="cpu", compute_type="int8")
    rows = []
    for tag, voice, ref in CASES:
        print(f"\n===== {tag.upper()} =====")
        mp3 = os.path.join(TMP, f"tts_{tag}.mp3")
        wav = os.path.join(TMP, f"tts_{tag}.wav")
        synth(ref, voice, mp3)
        to_pcm16k(mp3, wav)
        audio = load_audio(wav)
        dur = len(audio) / 16000
        print(f"音频时长 {dur:.2f}s")

        # 1) 整段识别（对照基线）
        segs, info = model.transcribe(audio, beam_size=1)
        text = "".join(s.text.strip() for s in segs).strip()
        err = cer(ref, text)
        hits = [k for k in KEYWORDS[tag] if k in text]
        print(f"[整段] 语种={info.language}({info.language_probability:.2f}) 字错率={err:.1%} 关键词={len(hits)}/{len(KEYWORDS[tag])}")
        print(f"       原文: {ref}")
        print(f"       识别: {text}")

        # 2) 5s 窗（模拟实时管道 WINDOW_SEC=5.0）
        win = audio[: 5 * 16000]
        segs_w, info_w = model.transcribe(
            win, vad_filter=True, vad_parameters={"min_silence_duration_ms": 400},
            beam_size=1, best_of=1)
        text_w = "".join(s.text.strip() for s in segs_w).strip()
        print(f"[5s窗] 语种={info_w.language}({info_w.language_probability:.2f}) 识别: {text_w}")

        rows.append((tag, info.language, info.language_probability, err, text, text_w))

        # 3) 抗噪：叠加白噪声（约 10dB SNR），模拟真实环境底噪
        rms = float(np.sqrt(np.mean(audio ** 2)))
        noise = np.random.normal(0, rms / 3.16, size=audio.shape).astype(np.float32)
        segs_n, info_n = model.transcribe(audio + noise, beam_size=1)
        text_n = "".join(s.text.strip() for s in segs_n).strip()
        print(f"[加噪10dB] 语种={info_n.language}({info_n.language_probability:.2f}) 字错率={cer(ref, text_n):.1%}")
        print(f"       识别: {text_n}")

        # 4) 翻译为中文（管道同款 Translator：gtx → clients5 → argos）
        from translator import Translator, detect_lang
        r = Translator().translate(text)
        zh_ok = "OK" if detect_lang(r.get("translated", "")) == "zh" else "未出中文"
        print(f"[翻译] 引擎={r.get('engine')} {zh_ok} 译文: {r.get('translated')}")
        if r.get("failed"):
            print(f"       失败原因: {str(r.get('error'))[:120]}")

    print("\n===== 汇总 =====")
    for tag, lang, prob, err, text, text_w in rows:
        ok_lang = "OK" if lang == tag else f"误判为 {lang}"
        print(f"{tag}: 语种 {ok_lang} 置信度 {prob:.2f} 字错率 {err:.1%}")


if __name__ == "__main__":
    main()
