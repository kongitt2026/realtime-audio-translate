# 端到端冒烟测试：
# 合成测试视频(TTS配音) → 起服务 → POST /api/play → WS 收字幕 → 校验中文字幕到达
# 用法：.venv\Scripts\python.exe tests\test_e2e.py [en|ja|ko]   默认 en
import asyncio
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(ROOT, "tests", "_tmp")
os.makedirs(TMP, exist_ok=True)
PORT = 8790

# 语种 → (测试台词, edge-tts 语音；None 表示走离线 pyttsx3 英文)
LANG = (sys.argv[1] if len(sys.argv) > 1 else "en").lower()
SCRIPTS = {
    "en": ("Hello everyone. The weather is very good today. "
           "We are going to the park this afternoon. Thank you very much.", None),
    "ja": ("皆さんこんにちは。今日はとても良い天気です。"
           "午後は公園に行きます。ありがとうございました。", "ja-JP-NanamiNeural"),
    "ko": ("안녕하세요 여러분. 오늘은 날씨가 정말 좋습니다. "
           "오후에 공원에 갑니다. 감사합니다.", "ko-KR-SunHiNeural"),
}
SCRIPT, VOICE = SCRIPTS[LANG]
VIDEO = os.path.join(TMP, f"test_video_{LANG}.mp4")

# ---- 1. 生成测试视频（TTS 语音 + 纯色画面，20 秒） ----
if not os.path.exists(VIDEO):
    print(f"[1] 生成 {LANG} 测试视频…")
    sys.path.insert(0, os.path.join(ROOT, "server"))
    from ffmpegbin import get_ffmpeg
    if VOICE:
        mp3 = os.path.join(TMP, f"speech_{LANG}.mp3")
        import edge_tts
        asyncio.run(edge_tts.Communicate(SCRIPT, VOICE).save(mp3))
        audio_in = mp3
    else:
        import pyttsx3
        audio_in = os.path.join(TMP, "speech.wav")
        eng = pyttsx3.init()
        eng.setProperty("rate", 130)
        eng.save_to_file(SCRIPT, audio_in)
        eng.runAndWait()
    subprocess.run([
        get_ffmpeg(), "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=navy:s=640x360:d=20",
        "-i", audio_in, "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", VIDEO
    ], check=True)
print(f"[1] 测试视频就绪: {os.path.getsize(VIDEO)//1024} KB")

# ---- 2. 启动服务 ----
print("[2] 启动服务…")
server = subprocess.Popen(
    [os.path.join(ROOT, ".venv", "Scripts", "python.exe"),
     os.path.join(ROOT, "server", "main.py")],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

async def run_check():
    import websockets
    import httpx
    # 等服务就绪
    for _ in range(60):
        try:
            r = httpx.get(f"http://127.0.0.1:{PORT}/api/status", timeout=1)
            if r.status_code == 200:
                break
        except Exception:
            pass
        await asyncio.sleep(0.5)
    else:
        raise RuntimeError("服务启动超时")
    print("[2] 服务已就绪")

    subs = []
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws") as ws:
        r = httpx.post(f"http://127.0.0.1:{PORT}/api/play",
                       json={"url": VIDEO}, timeout=15)
        assert r.status_code == 200 and r.json().get("ok"), f"play 失败: {r.text}"
        print(f"[3] 播放启动，player_url={r.json()['player_url']}，等待字幕（≤90s）…")
        t0 = time.time()
        while time.time() - t0 < 90:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            except asyncio.TimeoutError:
                continue
            if msg.get("type") == "subtitle":
                subs.append(msg)
                print(f"    [{time.time()-t0:5.1f}s] {msg.get('original','')[:50]}"
                      f" -> {msg.get('translated','')[:50]}"
                      f"  [engine={msg.get('engine')} failed={msg.get('failed')}]")
                if len(subs) >= 2:
                    break
    return subs

try:
    received = asyncio.run(run_check())
finally:
    server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()

# ---- 3. 判定 ----
assert received, "未收到任何字幕"
# 中文译文判定：含汉字且不含源语种字符（ja 假名 / ko 谚文），避免把日文汉字原文误判为中文
def is_zh(s: str) -> bool:
    has_cjk = any(0x4E00 <= ord(c) <= 0x9FFF for c in s)
    has_kana = any(0x3040 <= ord(c) <= 0x30FF for c in s)
    has_hangul = any(0xAC00 <= ord(c) <= 0xD7AF for c in s)
    return has_cjk and not has_kana and not has_hangul

zh_hit = [m for m in received if is_zh(m.get("translated", ""))]
print(f"[4] 收到字幕 {len(received)} 条，真中文译文 {len(zh_hit)} 条")
assert len(zh_hit) == len(received), "存在未译成中文的字幕（翻译降级）"

# 原文语种校验：ja 看假名、ko 看谚文
if LANG == "ja":
    assert any(any(0x3040 <= ord(c) <= 0x30FF for c in m.get("original", ""))
               for m in received), "未识别出日文原文"
elif LANG == "ko":
    assert any(any(0xAC00 <= ord(c) <= 0xD7AF for c in m.get("original", ""))
               for m in received), "未识别出韩文原文"
print("\n端到端冒烟测试通过 ✅  播放→ASR→翻译→WS推送 全链路闭环")
