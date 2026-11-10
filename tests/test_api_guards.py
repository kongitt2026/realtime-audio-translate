# 安全护栏验证：/api/play 协议白名单、/ws 来源校验
# 用法：先启动服务（启动.bat），再运行
#   .venv\Scripts\python.exe tests\test_api_guards.py
# 验什么：坏协议被 400 挡掉、外站 Origin 的 WebSocket 被拒、本地来源正常
import asyncio
import json
import sys

import httpx

BASE = "http://127.0.0.1:8790"
WS_BASE = "ws://127.0.0.1:8790"

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}{(' — ' + detail) if detail else ''}")


def play(client, url):
    return client.post(f"{BASE}/api/play", json={"url": url})


def test_play_guard():
    print("== /api/play 协议白名单 ==")
    bad = [
        ("file 协议", "file:///C:/Windows/win.ini"),
        ("concat 协议", "concat:/etc/passwd|/etc/hosts"),
        ("pipe 协议", "pipe:0"),
        ("data 协议", "data:audio/wav;base64,AAAA"),
        ("不存在的本地路径", r"Z:\definitely\not\here.mp4"),
    ]
    with httpx.Client(timeout=15) as client:
        for name, url in bad:
            r = play(client, url)
            body = {}
            try:
                body = json.loads(r.content.decode("utf-8"))
            except Exception:
                pass
            check(f"{name} 被拒绝", r.status_code == 400,
                  f"HTTP {r.status_code} {body.get('error', '')}")
            check(f"{name} 返回可读原因", bool(body.get("error")), str(body))

        r = play(client, "")
        check("空 url 被拒绝", r.status_code == 400, f"HTTP {r.status_code}")


def test_ws_origin():
    print("== /ws 来源校验 ==")
    try:
        import websockets
    except ImportError:
        print("  SKIP 未安装 websockets，跳过来源校验（pip install websockets 后可测）")
        return

    async def try_connect(origin):
        try:
            async with websockets.connect(f"{WS_BASE}/ws",
                                          additional_headers={"Origin": origin} if origin else None,
                                          open_timeout=10):
                return True
        except Exception:
            return False

    check("外站 Origin 被拒", not asyncio.run(try_connect("https://evil.example.com")))
    check("本机 Origin 放行", asyncio.run(try_connect("http://127.0.0.1:8790")))
    check("扩展 Origin 放行", asyncio.run(try_connect("chrome-extension://abcdefghijklmnop")))
    check("无 Origin（原生客户端）放行", asyncio.run(try_connect(None)))


def main():
    try:
        httpx.get(f"{BASE}/api/status", timeout=10)
    except Exception as e:
        print(f"[FATAL] 服务未启动或不可达：{e}")
        return 2

    test_play_guard()
    test_ws_origin()

    print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
