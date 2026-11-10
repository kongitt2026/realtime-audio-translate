# 实时翻译模块 · FastAPI 服务
# 端点：GET / 播放器页；WS /ws 字幕推送；POST /api/play {url}；POST /api/stop；GET /api/status
# 另有翻译自测端点：GET /api/engines（引擎/离线语种）、POST /api/translate {text}
# RTMP/RTSP 源自动转本地 HLS（浏览器不支持直连）；HTTP(S)/HLS/本地文件浏览器直链播放

import asyncio
import os
import subprocess
import sys
import threading
import time

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline import StreamPipeline  # noqa: E402
from browser_audio import create_pipeline  # noqa: E402
from ffmpegbin import get_ffmpeg  # noqa: E402
from subtitle_file import SubtitleParseError, parse_subtitles  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")
HLS_DIR = os.path.join(ROOT, "static_hls")
os.makedirs(HLS_DIR, exist_ok=True)

class Utf8JSONResponse(JSONResponse):
    """显式声明 charset：PowerShell 5 / 老客户端缺 charset 时按 Latin-1 解码会显示乱码。"""
    media_type = "application/json; charset=utf-8"


app = FastAPI(title="实时音视频翻译模块", default_response_class=Utf8JSONResponse)
app.mount("/static_hls", StaticFiles(directory=HLS_DIR), name="hls")

clients: set[WebSocket] = set()
pipeline: StreamPipeline | None = None
restream_proc: subprocess.Popen | None = None
loop: asyncio.AbstractEventLoop | None = None
_translator = None
_translator_lock = threading.Lock()


def get_translator():
    """进程内单例：初始化时探测 Argos 可用语种，装完离线包后需重启服务才生效。"""
    global _translator
    with _translator_lock:
        if _translator is None:
            from translator import Translator
            _translator = Translator()
        return _translator


def broadcast(payload: dict):
    """ASR 线程 → asyncio 主循环 安全广播"""
    if loop is None:
        return
    loop.call_soon_threadsafe(_broadcast_async, payload)


def _broadcast_async(payload: dict):
    dead = []
    for ws in list(clients):
        try:
            asyncio.ensure_future(ws.send_json(payload))
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


@app.get("/api/status")
def status():
    return {
        "running": pipeline is not None,
        "clients": len(clients),
        "restreaming": restream_proc is not None and restream_proc.poll() is None,
    }


@app.get("/api/engines")
def engines():
    """自测端点：返回翻译链与当前离线可译语种（用于确认服务已加载新装的 Argos 包）。"""
    return get_translator().health()


@app.post("/api/translate")
async def api_translate(body: dict):
    """自测端点：直接翻译一段文本，返回 {original, translated, lang, engine}。"""
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "text 不能为空"}, status_code=400)
    return {"ok": True, **get_translator().translate(text)}


@app.post("/api/subtitle/parse")
async def api_subtitle_parse(request: Request, name: str = ""):
    """解析上传的字幕文件原始字节（SRT / VTT / ASS-SSA），自动识别编码。

    为什么走服务端：日文字幕大量是 Shift_JIS(CP932)/EUC-JP，浏览器
    TextDecoder 只能按调用方指定的编码解码，无法自动判定；这里用
    charset_normalizer + 多编码打分兜底，统一转成 UTF-8 JSON 返回。
    """
    raw = await request.body()
    if not raw:
        return JSONResponse({"ok": False, "error": "请求体为空（应上传字幕文件原始字节）"},
                            status_code=400)
    try:
        return {"ok": True, "name": name, **parse_subtitles(raw, name)}
    except SubtitleParseError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:  # 解析器自身异常也要回给前端，不能只吐 500
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": f"解析失败: {e}"}, status_code=500)


@app.post("/api/play")
async def play(body: dict):
    global pipeline, restream_proc
    url = (body.get("url") or "").strip()
    if not url:
        return JSONResponse({"ok": False, "error": "url 不能为空"}, status_code=400)
    await stop()

    # 浏览器可播放的地址：http(s)/file 直链；rtmp/rtsp 转本地 HLS
    player_url = url
    scheme = url.split("://")[0].lower() if "://" in url else ("file" if os.path.exists(url) else "")
    if scheme in ("rtmp", "rtsp", "rtp"):
        live = os.path.join(HLS_DIR, "live.m3u8")
        if os.path.exists(live):
            os.remove(live)
        restream_proc = subprocess.Popen([
            get_ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", url,
            "-c", "copy", "-f", "hls", "-hls_time", "2", "-hls_list_size", "10",
            "-hls_flags", "delete_segments+append_list", live
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        player_url = "/static_hls/live.m3u8"

    def on_subtitle(result):
        broadcast({"type": "subtitle", **result})

    pipeline = StreamPipeline(url, on_subtitle)
    try:
        pipeline.start()
    except Exception as e:
        pipeline = None
        return JSONResponse({"ok": False, "error": f"启动失败: {e}"}, status_code=500)

    broadcast({"type": "status", "running": True, "source": url})
    return {"ok": True, "player_url": player_url, "scheme": scheme}


@app.post("/api/stop")
async def stop():
    global pipeline, restream_proc
    if pipeline:
        pipeline.stop()
        pipeline = None
    if restream_proc and restream_proc.poll() is None:
        restream_proc.kill()
    restream_proc = None
    broadcast({"type": "status", "running": False})
    return {"ok": True}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # 保持连接；客户端无需上行
    except WebSocketDisconnect:
        clients.discard(websocket)


@app.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket):
    """Chrome 扩展专用：上行 16kHz PCM16 单声道二进制分片，下行字幕 JSON。

    与 /ws 的区别：音频来自浏览器 tabCapture（可覆盖第三方站点的加密/登录态视频），
    不需要服务端再用 ffmpeg 拉流。
    """
    await websocket.accept()
    asyncio_loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def on_subtitle(result: dict):
        asyncio_loop.call_soon_threadsafe(q.put_nowait, result)

    pipe = create_pipeline(on_subtitle, lang=websocket.query_params.get("lang"))
    pipe.start()
    await websocket.send_json({"type": "status", "running": True, "mode": "browser"})

    async def sender():
        while True:
            item = await q.get()
            await websocket.send_json({"type": "subtitle", **item})

    sender_task = asyncio.create_task(sender())
    n_chunks = 0
    try:
        while True:
            data = await websocket.receive_bytes()
            n_chunks += 1
            pipe.feed(data)
    except WebSocketDisconnect:
        print(f"[ws/audio] 客户端断开，已收 {n_chunks} 块", flush=True)
    except Exception:
        # 这里绝不能静默吞异常：一旦接收循环挂掉，表现就是「有连接但永远 0 字幕」
        import traceback
        print(f"[ws/audio] 接收循环异常（已收 {n_chunks} 块）：", flush=True)
        traceback.print_exc()
    finally:
        if os.environ.get("LIVESUB_DEBUG"):
            try:
                print(f"[ws/audio] 管道统计 {pipe.stats()}", flush=True)
            except Exception:
                pass
        pipe.stop()
        sender_task.cancel()


def _warm_pipelines():
    """后台预热：whisper（语种嗅探/日韩通道）+ 翻译模型 + 流式 ASR 识别器。

    不做的话，首个 /ws/audio 连接要在 start() 里现加载：实测 whisper tiny
    冷启动 12.3s、Translator 冷启动 10.2s（含 LocalCT2 82MB 模型），这段时间
    音频只能排队，首条字幕被同样推后——表现为「有连接但很久不出字幕」。
    """
    try:
        import numpy as np
        from browser_audio import detect_language, get_model, get_translator
        get_model()          # 语种嗅探与日/韩通道都用它
        get_translator()     # 本地 CT2（含 82MB 模型）
        # 只加载权重不够：首个 transcribe 还要建计算图，实测首判 12.3s，
        # 会把第一条字幕拖到客户端都断开之后。这里跑一次哑推理把图热起来。
        t0 = time.monotonic()
        detect_language(np.zeros(16000, dtype=np.float32))
        print(f"[warmup] whisper 语种嗅探 + 多语种通道就绪"
              f"（首判预热 {(time.monotonic() - t0) * 1000:.0f}ms）", flush=True)
    except Exception:
        import traceback
        print("[warmup] 多语种通道预热失败（服务仍可用，首个连接会慢）：", flush=True)
        traceback.print_exc()

    try:
        from streaming_asr import model_available, warm_extra_langs, warm_up
        if not model_available("zh"):
            print("[warmup] 流式 zh/en 模型缺失，中英也走 whisper 通道", flush=True)
            return
        names = warm_up()
        print(f"[warmup] 流式 ASR 就绪 {names}", flush=True)
        # 日/韩识别器单独补热：首个日语/韩语连接不吃 1-4s 模型加载（首条延迟根因之一）
        warm_extra_langs()
    except Exception:
        import traceback
        print("[warmup] 流式 ASR 预热失败（服务仍可用，只是首个连接会慢）：", flush=True)
        traceback.print_exc()


@app.on_event("startup")
async def _capture_loop():
    global loop
    loop = asyncio.get_running_loop()
    threading.Thread(target=_warm_pipelines, daemon=True, name="warmup").start()


if __name__ == "__main__":
    import uvicorn
    print("实时音视频翻译模块 → http://127.0.0.1:8790")
    uvicorn.run(app, host="127.0.0.1", port=8790, log_level="warning")
