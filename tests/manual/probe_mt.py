import os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "server"))
from translator import Translator

tr = Translator()
for s in ["THE WEATHER IS", "THE WEATHER IS VERY", "THE WEATHER IS VERY GOOD",
          "WE ARE GOING TO THE PARK", "You just put your lips together"]:
    t = time.monotonic()
    r = tr.translate(s)
    print(f"{(time.monotonic()-t)*1000:.0f}ms engine={r['engine']} {r['translated']!r}", flush=True)
