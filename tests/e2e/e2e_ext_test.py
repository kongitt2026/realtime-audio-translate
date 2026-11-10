# -*- coding: utf-8 -*-
"""浏览器真机端到端实测：独立 Chrome 实例 + 未打包扩展 + B 站真实视频。

单进程自管 Chrome 生命周期（subprocess.Popen 启动 -> CDP 全流程 -> 结束 kill），
规避 Start-Process / & 启动的子进程在 shell 命令结束时被回收的问题。

用法：
  .venv\\Scripts\\python.exe tests\\e2e\\e2e_ext_test.py [video_url] [lang] [watch_sec]

输出：扩展是否启动、浮层字幕序列（含相对时间）、server.log 增量。
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import websockets

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXT = os.path.join(ROOT, "chrome_ext")
PORT = 9333
DEFAULT_URL = "https://www.bilibili.com/video/BV1zcWH6sEXv"
LOG = os.path.join(ROOT, "logs", "server.log")


# ---------------------------------------------------------------- CDP 基础

class Sess:
    def __init__(self, url):
        self.url = url
        self.ws = None
        self.n = 0

    async def open(self):
        self.ws = await websockets.connect(self.url, max_size=64 * 1024 * 1024)
        return self

    async def call(self, method, params=None, timeout=60):
        self.n += 1
        mid = self.n
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"{method} 超时")
            m = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=left))
            if m.get("id") == mid:
                return m

    async def eval(self, expr, timeout=60):
        r = await self.call("Runtime.evaluate",
                            {"expression": expr, "returnByValue": True, "awaitPromise": True},
                            timeout=timeout)
        res = r.get("result") or {}
        if r.get("error"):
            return {"__error": r["error"]}
        if (res.get("exceptionDetails")):
            return {"__exception": res["exceptionDetails"].get("text"),
                    "desc": (((res["exceptionDetails"].get("exception") or {}).get("description")) or "")[:300]}
        return res.get("result", {}).get("value")

    async def close(self):
        try:
            await self.ws.close()
        except Exception:
            pass


def http_json(path, timeout=3):
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=timeout).read().decode())


def wait_port(limit=30.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        try:
            return http_json("/json/version")
        except Exception:
            time.sleep(0.4)
    raise RuntimeError("Chrome 调试端口未就绪")


def find_target(kind, url_part=None):
    try:
        items = http_json("/json/list")
    except Exception:
        return None
    for it in items:
        if it.get("type") != kind:
            continue
        if url_part and url_part not in (it.get("url") or ""):
            continue
        return it
    return None


def blank_chrome():
    return subprocess.Popen(
        [CHROME,
         f"--remote-debugging-port={PORT}",
         f"--user-data-dir={os.path.expanduser('~')}\\.cache\\livesub-e2e-p{int(time.time())}",
         "--no-first-run", "--no-default-browser-check", "--disable-sync",
         "--autoplay-policy=no-user-gesture-required",
         "--enable-unsafe-extension-debugging",
         "--disable-blink-features=AutomationControlled",
         "--window-size=1280,820", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- 主流程

PROBE_OVERLAY = """(() => {
  const h = document.getElementById('__live_subtitle_host__');
  if (!h || !h.shadowRoot) return '';
  const o = h.shadowRoot.querySelector('.orig');
  const t = h.shadowRoot.querySelector('.tran');
  const s = [o ? o.textContent : '', t ? t.textContent : ''].join(' | ');
  return s.trim() === '|' ? '' : s;
})()"""

PROBE_VIDEO = """(() => {
  const v = document.querySelector('video');
  if (!v) return JSON.stringify({has:false, href:location.href, title:document.title});
  return JSON.stringify({has:true, paused:v.paused, t:+v.currentTime.toFixed(2),
    rs:v.readyState, dur:v.duration, err:v.error?v.error.code:null,
    href:location.href, title:document.title.slice(0,60)});
})()"""


async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    lang = sys.argv[2] if len(sys.argv) > 2 else "ja"
    watch = int(sys.argv[3]) if len(sys.argv) > 3 else 50

    base_lines = 0
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8", errors="replace") as f:
            base_lines = sum(1 for _ in f)
    print(f"[0] server.log 基线行数={base_lines}  url={url} lang={lang} watch={watch}s", flush=True)

    proc = blank_chrome()
    try:
        ver = wait_port(30)
        print(f"[1] Chrome 就绪 {ver.get('Browser')}  pid={proc.pid}", flush=True)

        br = await Sess(ver["webSocketDebuggerUrl"]).open()
        r = await br.call("Extensions.loadUnpacked", {"path": EXT})
        ext = (r.get("result") or {})
        ext_id = ext.get("id")
        print(f"[2] loadUnpacked -> {json.dumps(ext, ensure_ascii=False)}", flush=True)
        if not ext_id:
            print("!! 扩展装载失败，终止", flush=True)
            return

        # 打开视频页
        tgt = find_target("page")
        if not tgt:
            r = await br.call("Target.createTarget", {"url": "about:blank"})
            await asyncio.sleep(1)
            tgt = find_target("page")
        page = await Sess(tgt["webSocketDebuggerUrl"]).open()
        await page.call("Page.enable")
        await page.call("Page.navigate", {"url": url})
        print(f"[4] navigate -> {url}", flush=True)

        # 等视频进入播放
        played = False
        t0 = time.monotonic()
        while time.monotonic() - t0 < 45:
            await asyncio.sleep(1)
            v = await page.eval(PROBE_VIDEO)
            try:
                st = json.loads(v) if isinstance(v, str) else {}
            except Exception:
                st = {}
            if st.get("has") and st.get("paused"):
                # 不能 muted：tabCapture 抓的是标签页实际输出的声音，元素静音 = 抓到静音
                await page.eval("(()=>{const v=document.querySelector('video');"
                                "v.muted=false;if(v.volume<0.05)v.volume=1;"
                                "v.play().catch(()=>{});})()")
                await page.eval("(()=>{const b=document.querySelector('.bpx-player-ctrl-play');if(b)b.click();})()")
            if st.get("has") and not st.get("paused") and (st.get("t") or 0) > 1:
                print(f"[5] 视频播放中 {json.dumps(st, ensure_ascii=False)}", flush=True)
                played = True
                break
        if not played:
            v = await page.eval(PROBE_VIDEO)
            print(f"[5] 视频未能自动播放，仍继续尝试。state={v}", flush=True)

        # 确保未静音（tabCapture 抓标签页实际输出的声音）
        print("[5b] 播放状态 " + str(await page.eval(
            "(()=>{const v=document.querySelector('video');"
            "return JSON.stringify({muted:v.muted,vol:v.volume,paused:v.paused,t:+v.currentTime.toFixed(1)});})()")), flush=True)

        # YouTube 前置广告：ad-showing 期间 tabCapture 抓到的是广告音频，必须等广告结束
        t_ad = time.monotonic()
        while time.monotonic() - t_ad < 90:
            ad = await page.eval(
                "(()=>{const p=document.querySelector('#movie_player');"
                "const v=document.querySelector('video');"
                "return JSON.stringify({ad:!!(p&&p.classList.contains('ad-showing')),"
                "dur:v?(v.duration||0):0});})()")
            try:
                ast = json.loads(ad) if isinstance(ad, str) else {}
            except Exception:
                ast = {}
            if ast.get("ad"):
                print(f"[5c] 广告播放中 dur={ast.get('dur')}，等待…", flush=True)
                await asyncio.sleep(2)
                continue
            if (ast.get("dur") or 0) > 120:
                break
            await asyncio.sleep(1.5)
        print(f"[5c] 广告结束/正片 dur={ast.get('dur')}", flush=True)

        # 授予 activeTab：模拟用户点击扩展图标（必须传 type=tab 的 targetId）
        # tab 目标默认不在 discover filter 里，必须先声明再查询
        await br.call("Target.setDiscoverTargets", {"discover": True, "filter": [{"type": "tab"}]})
        await asyncio.sleep(0.6)
        tabs = [t for t in (await br.call("Target.getTargets", {"filter": [{"type": "tab"}]}))
                .get("result", {}).get("targetInfos", []) if t.get("type") == "tab"]
        host = urllib.parse.urlsplit(url).netloc
        tb = next((t for t in tabs if host and host in (t.get("url") or "")),
                  next((t for t in tabs if "bilibili" in (t.get("url") or "")), tabs[0] if tabs else None))
        print(f"[6] tab targets={len(tabs)} 选中={(tb or {}).get('targetId')} url={(tb or {}).get('url','')[:60]}", flush=True)
        r = await br.call("Extensions.triggerAction",
                          {"id": ext_id, "targetId": (tb or {}).get("targetId")})
        print(f"[6] triggerAction -> {json.dumps(r.get('result'), ensure_ascii=False)} err={r.get('error')}", flush=True)
        await asyncio.sleep(1.0)

        # 在 Service Worker 里直接调 toggle(tabId, lang)
        started = False
        for attempt in range(2):
            sw = find_target("service_worker", ext_id)
            if not sw:
                # 打开扩展页面唤醒 SW
                await br.call("Target.createTarget", {"url": f"chrome-extension://{ext_id}/popup.html"})
                await asyncio.sleep(1.5)
                sw = find_target("service_worker", ext_id)
            if not sw:
                print(f"[7] 第{attempt+1}次：未找到 service_worker target", flush=True)
                continue
            print(f"[7] service_worker -> {sw.get('url')}", flush=True)
            s = await Sess(sw["webSocketDebuggerUrl"]).open()
            out = await s.eval(
                "(async () => {"
                "  const [t] = await chrome.tabs.query({active:true, currentWindow:true});"
                f"  const r = await toggle(t.id, '{lang}');"
                "  return JSON.stringify({tabId: t.id, url: t.url, r});"
                "})()", timeout=90)
            print(f"[8] toggle -> {out}", flush=True)
            await s.close()
            if isinstance(out, str) and '"running":true' in out.replace(" ", ""):
                started = True
                break
            await asyncio.sleep(1)

        if not started:
            print("[!] 自动启动失败，回退：请人工点扩展图标。", flush=True)

        t_start = time.monotonic()
        print(f"[9] 开始观测浮层字幕（{watch}s）", flush=True)
        last = ""
        first_at = None
        rows = []
        while time.monotonic() - t_start < watch:
            await asyncio.sleep(0.15)
            txt = await page.eval(PROBE_OVERLAY)
            if not isinstance(txt, str):
                txt = ""
            if txt and txt != last:
                dt = (time.monotonic() - t_start) * 1000
                if first_at is None:
                    first_at = dt
                rows.append((dt, txt))
                print(f"    SUB +{dt:6.0f}ms  {txt}", flush=True)
                last = txt
            elif not txt:
                last = ""

        print("[10] 汇总", flush=True)
        print(f"    首个字幕到达 = {first_at:.0f}ms" if first_at else "    无字幕产出（浮层为空）", flush=True)
        print(f"    字幕条数 = {len(rows)}", flush=True)
        await page.close()
        await br.close()
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # 服务端日志增量
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        delta = lines[base_lines:]
        print(f"[11] server.log 新增 {len(delta)} 行，其中关键行：", flush=True)
        keys = ("latency", "管道统计", "客户端连接", "客户端断开", "final", "lang=", "错误", "Traceback")
        for ln in delta:
            if any(k in ln for k in keys):
                print("    " + ln.rstrip(), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
