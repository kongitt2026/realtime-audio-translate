# 语种路由探针：进程内直接跑 LangRoutePipeline，打印判定/异常/产出
# 运行：.venv\Scripts\python.exe tests\manual\probe_route.py [wav路径]

import os
import subprocess
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "server"))

import browser_audio  # noqa: E402


def wav_to_pcm(path: str) -> bytes:
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    out = subprocess.run([ff, "-v", "error", "-i", path, "-f", "s16le",
                          "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True)
    return out.stdout


def main():
    wav = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tests", "fixtures", "tts_ja.wav")
    pcm = wav_to_pcm(wav)
    dur = len(pcm) / 32000.0
    print(f"素材 {os.path.basename(wav)}  {len(pcm)} bytes  {dur:.2f}s", flush=True)

    sniff = np.frombuffer(pcm[:browser_audio.SNIFF_BYTES], dtype=np.int16).astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(sniff ** 2)))
    print(f"前 {len(sniff) / 16000:.2f}s RMS={rms:.1f}  (门限 {browser_audio.RMS_GATE})", flush=True)
    t0 = time.time()
    lang, prob = browser_audio.detect_language(sniff)
    print(f"detect_language → lang={lang!r} prob={prob:.3f}  耗时 {time.time() - t0:.2f}s", flush=True)

    subs = []
    pipe = browser_audio.create_pipeline(lambda r: (subs.append(r),
                                                    print("  SUB:", r, flush=True)))
    print(f"pipeline={type(pipe).__name__}", flush=True)
    pipe.start()
    for i in range(0, len(pcm), 8192):
        pipe.feed(pcm[i:i + 8192])
        time.sleep(0.25)
    time.sleep(15)
    pipe.stop()
    print(f"\n产出 {len(subs)} 条，stats={pipe.stats()}", flush=True)


if __name__ == "__main__":
    main()
