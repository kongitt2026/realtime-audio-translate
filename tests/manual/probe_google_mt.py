import time
import httpx

TEXT = "THE WEATHER IS VERY GOOD"
URL_GTX = "https://translate.googleapis.com/translate_a/single"
PARAMS = {"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": TEXT}


def probe(name, client):
    try:
        t = time.monotonic()
        r = client.get(URL_GTX, params=PARAMS, timeout=6.0,
                       headers={"User-Agent": "Mozilla/5.0"})
        ms = (time.monotonic() - t) * 1000
        body = r.text[:120].replace("\n", " ")
        print(f"{name}: {r.status_code} {ms:.0f}ms {body!r}", flush=True)
    except Exception as e:
        print(f"{name}: ERR {type(e).__name__} {e}", flush=True)


probe("direct", httpx.Client(trust_env=False))
probe("env", httpx.Client())
probe("proxy7890", httpx.Client(proxy="http://127.0.0.1:7890", trust_env=False))
