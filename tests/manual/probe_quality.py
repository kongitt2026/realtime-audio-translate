import os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from offline_translate.engines import LocalCT2
from offline_translate import Translator
local = LocalCT2()
for s in ["THE WEATHER IS VERY GOOD", "the weather is very good",
          "THE WEATHER IS VERY GOOD TO THE END WE ARE GOING TO THE PARK",
          "the weather is very good to the end we are going to the park"]:
    t=time.monotonic(); out=local.translate(s, "en", "zh-CN")
    print(f"{int((time.monotonic()-t)*1000)}ms {s!r} -> {out!r}")
tr = Translator(timeout=1.2)
for s in ["the weather is very good", "I think this video is really interesting"]:
    t=time.monotonic(); r=tr.translate(s)
    print(f"chain {int((time.monotonic()-t)*1000)}ms engine={r.get('engine')} {r.get('translated')!r} failed={r.get('failed')}")
print(tr.health())
