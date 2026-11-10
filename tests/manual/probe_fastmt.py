import os
import time

import ctranslate2
import sentencepiece as spm

PKG = os.path.expanduser(r"~\.local\share\argos-translate\packages\translate-en_zh-1_9")
sp = spm.SentencePieceProcessor(model_file=os.path.join(PKG, "sentencepiece.model"))
t0 = time.monotonic()
tr = ctranslate2.Translator(os.path.join(PKG, "model"), device="cpu", compute_type="int8",
                            inter_threads=1, intra_threads=4)
print(f"load={(time.monotonic()-t0)*1000:.0f}ms")

tests = ["The weather is very good", "We are going to the park",
         "You just put your lips together", "The weather is very good to the end we are going to the park"]
for s in tests:
    for beam in (1,):
        t = time.monotonic()
        toks = sp.encode(s, out_type=str)
        out = tr.translate_batch([toks], beam_size=beam, max_decoding_length=128)
        zh = sp.decode(out[0].hypotheses[0])
        print(f"{(time.monotonic()-t)*1000:6.1f}ms beam={beam} {s!r} -> {zh!r}", flush=True)
