# 浏览器端到端验证（不经 GUI 点击）：独立 Chrome 实例 + CDP 直接调用扩展 start()
# 目的：拿到「真实 tabCapture 音频 → WS → 流式 ASR → 翻译 → 字幕回推」的端到端延迟
import json
import os
import subprocess
import sys
import time
import urllib.request

from websockets.sync.client import connect

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXT = os.environ.get("LIVESUB_EXT") or os.path.join(ROOT, "chrome_ext")
PROFILE = os.environ.get("CDP_PROFILE") or os.path.join(ROOT, "tests", "_tmp", "cdpprofile2")
PORT = int(os.environ.get("CDP_PORT", "9444"))
TEST_URL = "http://127.0.0.1:18791/"
LOG = os.path.join(ROOT, "logs", "server.log")


def http_json(path):
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=3) as r:
        return json.loads(r.read().decode("utf-8"))


class CDP:
    def __init__(self, url):
        self.ws = connect(url, max_size=32 * 1024 * 1024, open_timeout=10)
        self.i = 0

    def send(self, method, params=None, session=None):
        self.i += 1
        msg = {"id": self.i, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        self.ws.send(json.dumps(msg))
        while True:
            data = json.loads(self.ws.recv(timeout=30))
            if data.get("id") == self.i:
                return data

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def wait_devtools(deadline=30):
    t0 = time.time()
    while time.time() - t0 < deadline:
        try:
            return http_json("/json/version")
        except Exception:
            time.sleep(0.5)
    raise SystemExit("DevTools 端口未就绪")


def ext_id_from_profile(ext_path):
    """从 Secure Preferences 里按安装路径反查扩展 ID（临时实例的 ID 由路径决定）。"""
    p = os.path.join(PROFILE, "Default", "Secure Preferences")
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    settings = (data.get("extensions") or {}).get("settings") or {}
    norm = os.path.normcase(os.path.normpath(ext_path)).lower()
    for eid, info in settings.items():
        path = (info or {}).get("path")
        if path and os.path.normcase(os.path.normpath(path)).lower() == norm:
            return eid
    return None


def find_sw(cdp, deadline=10, ext_id=None):
    t0 = time.time()
    while time.time() - t0 < deadline:
        infos = cdp.send("Target.getTargets")["result"]["targetInfos"]
        sw = [t for t in infos if t["type"] == "service_worker"
              and "chrome-extension://" in t["url"] and t["url"].endswith("/background.js")
              and (not ext_id or f"chrome-extension://{ext_id}/" in t["url"])]
        if sw:
            return sw[0], infos
        time.sleep(1)
    return None, cdp.send("Target.getTargets")["result"]["targetInfos"]


def main():
    args = [
        CHROME,
        f"--user-data-dir={PROFILE}",
    ]
    if not os.environ.get("CDP_NO_LOAD_EXT"):
        args += [
            f"--load-extension={EXT}",
            f"--disable-extensions-except={EXT}",
            # Chrome 137+ 默认禁用命令行的 --load-extension，需要显式解禁
            "--disable-features=DisableLoadExtensionCommandLineSwitch",
        ]
    args += [
        f"--remote-debugging-port={PORT}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--autoplay-policy=no-user-gesture-required",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        TEST_URL,
    ]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[cdp] chrome pid={proc.pid} profile={PROFILE}", flush=True)
    try:
        ver = wait_devtools()
        print(f"[cdp] {ver.get('Browser')}", flush=True)

        cdp = CDP(ver["webSocketDebuggerUrl"])
        cdp.send("Target.setDiscoverTargets", {"discover": True})
        time.sleep(3)  # 等页面加载 + 扩展 SW 启动

        eid = ext_id_from_profile(EXT)
        print(f"[cdp] ext_id={eid}", flush=True)
        sw_t, targets = find_sw(cdp, 8, eid)
        if not sw_t:
            print("[cdp] SW 未启动，尝试 chrome-extension://<id>/offscreen.html 唤醒", flush=True)
            if eid:
                cdp.send("Target.createTarget", {"url": f"chrome-extension://{eid}/offscreen.html"})
            sw_t, targets = find_sw(cdp, 10, eid)
        for t in targets:
            print(f"[target] {t['type']:<16} {t['url'][:110]}", flush=True)
        page = [t for t in targets if t["type"] == "page" and "127.0.0.1:18791" in t["url"]]
        if not sw_t:
            raise SystemExit("未发现扩展 Service Worker 目标（扩展可能未加载）")
        sw = [sw_t]
        print(f"[cdp] SW={sw[0]['url']}", flush=True)

        # 先确认测试页音频真的在播（否则 tabCapture 抓到的是静音）
        if page:
            ps = cdp.send("Target.attachToTarget", {"targetId": page[0]["targetId"], "flatten": True})
            psess = ps["result"]["sessionId"]
            cdp.send("Runtime.enable", {}, psess)
            cdp.send("Runtime.evaluate", {"expression": "(()=>{const a=document.querySelector('audio');if(!a)return 'no-audio';if(a.paused)a.play().catch(()=>{});return 'ok'})()",
                                          "returnByValue": True}, psess)
            time.sleep(1.0)
            r = cdp.send("Runtime.evaluate", {"expression": "(()=>{const a=document.querySelector('audio');return a?{paused:a.paused,t:+a.currentTime.toFixed(2),muted:a.muted,vol:a.volume}:'none'})()",
                                              "returnByValue": True}, psess)
            print("[page]", json.dumps(r.get("result", {}).get("result", {}).get("value"), ensure_ascii=False), flush=True)

        size0 = os.path.getsize(LOG) if os.path.exists(LOG) else 0

        att = cdp.send("Target.attachToTarget", {"targetId": sw[0]["targetId"], "flatten": True})
        sess = att["result"]["sessionId"]
        cdp.send("Runtime.enable", {}, sess)

        expr = """(async () => {
          try {
            const tabs = await chrome.tabs.query({});
            if (!tabs.length) return {error: 'no-tabs'};
            const t = tabs.find(x => x.url && x.url.includes('127.0.0.1:18791')) || tabs[0];
            await start(t);
            return {ok: true, tabId: t.id, url: t.url, n: tabs.length};
          } catch (e) { return {error: String((e && e.message) || e)}; }
        })()"""
        r = cdp.send("Runtime.evaluate",
                     {"expression": expr, "awaitPromise": True, "returnByValue": True}, sess)
        print("[start]", json.dumps(r.get("result", r), ensure_ascii=False), flush=True)

        # 等音频循环跑几轮，期间观察字幕是否到达
        for i in range(1, 13):
            time.sleep(1)
            st = cdp.send("Runtime.evaluate", {
                "expression": "(async()=>{const c=await chrome.runtime.getContexts({contextTypes:['OFFSCREEN_DOCUMENT']});return c.length})()",
                "awaitPromise": True, "returnByValue": True}, sess)
            print(f"[wait] {i}s offscreen_ctxs={st.get('result',{}).get('result',{}).get('value')}", flush=True)
        cdp.close()

        print("\n===== 服务端新增日志 =====", flush=True)
        if os.path.exists(LOG):
            with open(LOG, "rb") as f:
                f.seek(size0)
                txt = f.read().decode("utf-8", "replace")
            for line in txt.splitlines():
                if "[stream]" in line or "[ws/audio]" in line or "traceback" in line.lower():
                    print(line, flush=True)
    finally:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[cdp] 已关闭临时 Chrome pid={proc.pid}", flush=True)


if __name__ == "__main__":
    main()
