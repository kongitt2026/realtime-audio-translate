import time
import httpx

TEXT = "THE WEATHER IS VERY GOOD"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"}


def timed(name, fn):
    t = time.monotonic()
    try:
        r = fn()
        print(f"{name}: {r}  ({(time.monotonic()-t)*1000:.0f}ms)", flush=True)
    except Exception as e:
        print(f"{name}: ERR {type(e).__name__} {e}  ({(time.monotonic()-t)*1000:.0f}ms)", flush=True)


for label, client in [("direct", httpx.Client(trust_env=False, timeout=8.0)),
                      ("proxy", httpx.Client(proxy="http://127.0.0.1:7890", trust_env=False, timeout=8.0))]:
    # 1) clients5 dict-chrome-ex
    def f1(c=client):
        r = c.get("https://clients5.google.com/translate_a/t",
                  params={"client": "dict-chrome-ex", "sl": "auto", "tl": "zh-CN", "q": TEXT},
                  headers=UA)
        return f"{r.status_code} {r.text[:80]!r}"
    timed(f"{label}/clients5", f1)

    # 2) edge microsoft auth + translate
    def f2(c=client):
        a = c.get("https://edge.microsoft.com/translate/auth", headers=UA)
        if a.status_code != 200:
            return f"auth {a.status_code} {a.text[:60]!r}"
        tok = a.text.strip()
        r = c.post("https://api-edge.cognitive.microsofttranslator.com/translate",
                   params={"api-version": "3.0", "to": "zh-Hans"},
                   headers={**UA, "Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                   json=[{"Text": TEXT}])
        return f"auth200 token_len={len(tok)} -> {r.status_code} {r.text[:100]!r}"
    timed(f"{label}/msedge", f2)

    # 3) MyMemory
    def f3(c=client):
        r = c.get("https://api.mymemory.translated.net/get",
                  params={"q": TEXT, "langpair": "en|zh-CN"}, headers=UA)
        return f"{r.status_code} {r.text[:100]!r}"
    timed(f"{label}/mymemory", f3)
