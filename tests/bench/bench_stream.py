"""流式 ASR 管道离线基准：按真实节奏（256ms/块）喂 16k 单声道 wav，统计字幕延迟。

用法：
  .venv\\Scripts\\python.exe tests\\bench\\bench_stream.py tests\\fixtures\\speech.wav
输出：每条字幕的 latency_ms（从该句最后一块音频到达 → 字幕产出），以及汇总。
"""
import os
import sys
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "server"))

import numpy as np  # noqa: E402

from streaming_asr import (  # noqa: E402
    StreamingAudioPipeline, build_translators, get_recognizer, model_available,
)


def load_wav(path):
    with wave.open(path, "rb") as w:
        assert w.getframerate() == 16000, w.getframerate()
        assert w.getnchannels() == 1, w.getnchannels()
        assert w.getsampwidth() == 2, w.getsampwidth()
        return w.readframes(w.getnframes())


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tests", "fixtures", "speech.wav")
    chunk_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 256
    lead_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
    lang = sys.argv[4] if len(sys.argv) > 4 else "zh"
    print(f"model_available={model_available(lang)} lang={lang} wav={path} "
          f"chunk={chunk_ms}ms lead={lead_ms}ms", flush=True)

    rows = []

    def on_subtitle(r):
        rows.append((time.monotonic(), r))
        tag = "final" if not r.get("partial") else "partial"
        print(f"  [{tag}] latency_ms={r.get('latency_ms')} engine={r.get('engine')} "
              f"orig={r.get('original')[:60]!r} tran={str(r.get('translated'))[:40]!r}", flush=True)

    pcm = load_wav(path)
    # 服务端启动时会预热识别器与翻译链；基准里同样先加载，否则冷启动时间会被算进
    # 首条字幕延迟（实测：ja 模型加载 18-31s、CT2 翻译首句预热 2-5s）
    get_recognizer(lang)
    build_translators()
    p = StreamingAudioPipeline(on_subtitle, lang=lang)
    p.start()
    # 模拟真实使用：用户按下快捷键（start）→ 视频再开始出声。
    # 模型预热/熔断预热都在这段空窗内完成，不占用字幕延迟。
    if lead_ms > 0:
        time.sleep(lead_ms / 1000)

    bytes_per_chunk = int(16000 * 2 * chunk_ms / 1000)
    t_start = time.monotonic()
    for i in range(0, len(pcm), bytes_per_chunk):
        p.feed(pcm[i:i + bytes_per_chunk])
        # 按真实时长推进
        target = t_start + (i + bytes_per_chunk) / (16000 * 2)
        sleep = target - time.monotonic()
        if sleep > 0:
            time.sleep(sleep)

    audio_seconds = len(pcm) / (16000 * 2)
    print(f"音频喂完，用时 {time.monotonic() - t_start:.2f}s（音频时长 {audio_seconds:.2f}s），"
          f"等待 3s 收尾…", flush=True)
    time.sleep(3.0)
    p.stop()
    time.sleep(0.5)

    lat = [r["latency_ms"] for _, r in rows if r.get("latency_ms") is not None]
    finals = [r for _, r in rows if not r.get("partial")]
    print("\n=== 汇总 ===")
    print(f"字幕条数={len(rows)}（final={len(finals)} / partial={len(rows) - len(finals)}）")
    if lat:
        print(f"latency_ms: min={min(lat)} avg={sum(lat) // len(lat)} max={max(lat)}")
    st = p.stats()
    print(f"块数={st['chunks']} 平均解码={st['decode_ms'] / max(1, st['chunks']):.1f}ms "
          f"首条字幕={st['first_subtitle_ms']}ms")
    print("最终字幕：")
    for r in finals:
        print(f"  - {r.get('original')!r} → {r.get('translated')!r}")


if __name__ == "__main__":
    main()
