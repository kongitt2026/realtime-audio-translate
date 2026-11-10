# 下载 ja/ko 流式 ASR 模型（GitHub release tar.bz2）并解压
# 用 Python 而非 PowerShell 脚本：路径含中文，ps1 默认按 GBK 读取会解析失败
import os
import tarfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DL = os.path.join(ROOT, "models")
BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
ITEMS = [
    ("sherpa-onnx-streaming-zipformer-ar_en_id_ja_ru_th_vi_zh-2025-02-10", 258999581),
    ("sherpa-onnx-streaming-zipformer-korean-2024-06-16", 418218652),
]


def download(name, expect):
    tar = os.path.join(DL, name + ".tar.bz2")
    if os.path.exists(tar) and abs(os.path.getsize(tar) - expect) < 1024 * 1024:
        print(f"[dl] 已存在完整包 {name}", flush=True)
        return tar
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(
                BASE + name + ".tar.bz2", headers={"User-Agent": "Mozilla/5.0"}
            )
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=60) as r, open(tar, "wb") as f:
                total = int(r.headers.get("Content-Length") or expect)
                got = last = 0
                while True:
                    buf = r.read(1 << 20)
                    if not buf:
                        break
                    f.write(buf)
                    got += len(buf)
                    if got - last >= 40 * 1024 * 1024:
                        last = got
                        speed = got / max(time.time() - t0, 1e-6) / 1e6
                        print(f"  {got/1e6:.0f}/{total/1e6:.0f}MB {speed:.1f}MB/s", flush=True)
            if os.path.getsize(tar) == total:
                print(f"[dl] 完成 {name} {total/1e6:.0f}MB {time.time()-t0:.0f}s", flush=True)
                return tar
            print(f"[dl] 大小不符 {os.path.getsize(tar)} != {total}", flush=True)
        except Exception as exc:
            print(f"[dl] 第{attempt}次异常 {exc!r}", flush=True)
            time.sleep(3)
    return None


def extract(tar):
    t0 = time.time()
    with tarfile.open(tar, "r:bz2") as tf:
        tf.extractall(DL, filter="data")
    print(f"[ex] 解压完成 {time.time()-t0:.0f}s", flush=True)


for name, expect in ITEMS:
    print(f"=== {name} ===", flush=True)
    path = download(name, expect)
    if path is None:
        print(f"[!] {name} 下载失败", flush=True)
        continue
    extract(path)
    os.remove(path)          # 解压后删包，省 ~600MB
    d = os.path.join(DL, name)
    for fn in sorted(os.listdir(d)):
        fp = os.path.join(d, fn)
        if os.path.isfile(fp):
            print(f"  {fn}  {os.path.getsize(fp)/1e6:.1f}MB", flush=True)
print("=== DONE ===", flush=True)
