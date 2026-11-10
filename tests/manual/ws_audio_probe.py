import asyncio
import json
import subprocess
import sys
import time

import imageio_ffmpeg
import websockets

FF = imageio_ffmpeg.get_ffmpeg_exe()


def to_pcm(path: str) -> bytes:
    r = subprocess.run(
        [FF, "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True,
    )
    return r.stdout


async def main(path: str, lang: str = ""):
    data = to_pcm(path)
    url = "ws://127.0.0.1:8790/ws/audio" + (f"?lang={lang}" if lang else "")
    print(f"pcm_bytes={len(data)} dur={len(data)/32000:.2f}s url={url}", flush=True)
    t0 = time.monotonic()
    async with websockets.connect(url) as ws:
        async def recv():
            while True:
                raw = await ws.recv()
                m = json.loads(raw)
                if m.get("type") == "subtitle":
                    now = (time.monotonic() - t0) * 1000
                    print(f"SUB wall={now:.0f}ms latency_ms={m.get('latency_ms')}ms "
                          f"partial={m.get('partial')} engine={m.get('engine')} "
                          f"orig={m.get('original')} tran={m.get('translated')}", flush=True)

        task = asyncio.create_task(recv())
        chunk = 8000  # 0.25s
        for i in range(0, len(data), chunk):
            await ws.send(data[i:i + chunk])
            await asyncio.sleep(0.25)
        print("stream_end", flush=True)
        await asyncio.sleep(4)
        task.cancel()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""))
