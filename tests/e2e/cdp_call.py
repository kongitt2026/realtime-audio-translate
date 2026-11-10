"""通用 CDP 调用器：把一组 {method, params} 依次发给浏览器/页面目标并打印结果。

用法：
  python tests/e2e/cdp_call.py browser '[{"method":"Extensions.loadUnpacked","params":{"path":"..."}}]'
  python tests/e2e/cdp_call.py <pageWsUrl> '[{"method":"Runtime.evaluate","params":{"expression":"1+1"}}]'
"""
import asyncio
import json
import sys
import urllib.request

import websockets


def resolve(target: str) -> str:
    if target.startswith("ws://"):
        return target
    url = "http://127.0.0.1:9333/json/version" if target == "browser" else "http://127.0.0.1:9333/json/list"
    data = json.loads(urllib.request.urlopen(url, timeout=5).read().decode())
    if target == "browser":
        return data["webSocketDebuggerUrl"]
    pages = [p for p in data if p.get("type") == "page"]
    return pages[0]["webSocketDebuggerUrl"]


async def main(target: str, calls: str):
    ws_url = resolve(target)
    if calls.startswith("@"):
        with open(calls[1:], encoding="utf-8") as f:
            cmds = json.load(f)
    else:
        cmds = json.loads(calls)
    async with websockets.connect(ws_url, max_size=32 * 1024 * 1024) as ws:
        for i, c in enumerate(cmds, 1):
            await ws.send(json.dumps({"id": i, "method": c["method"], "params": c.get("params", {})}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                if msg.get("id") == i:
                    print(json.dumps({"seq": i, "method": c["method"], "result": msg.get("result"), "error": msg.get("error")}, ensure_ascii=False)[:2000], flush=True)
                    break


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
