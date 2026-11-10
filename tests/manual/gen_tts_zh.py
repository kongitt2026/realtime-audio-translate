# 生成中文回归素材：edge-tts 在线合成（免费、无 Key）→ 16k 单声道 wav
import asyncio
import os
import subprocess
import sys

import edge_tts
import imageio_ffmpeg

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = os.path.join(ROOT, "tests", "_tmp")

TEXT = "今天天气非常好，我们一起去公园散步吧。"
VOICE = "zh-CN-XiaoxiaoNeural"


def main():
    os.makedirs(TMP, exist_ok=True)
    mp3 = os.path.join(TMP, "tts_zh.mp3")
    wav = os.path.join(TMP, "tts_zh.wav")
    asyncio.run(edge_tts.Communicate(TEXT, VOICE).save(mp3))
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ff, "-y", "-v", "error", "-i", mp3, "-ac", "1", "-ar", "16000", wav],
                   check=True)
    print(f"生成 {wav}  {os.path.getsize(wav)} bytes  文本={TEXT}")


if __name__ == "__main__":
    sys.exit(main())
