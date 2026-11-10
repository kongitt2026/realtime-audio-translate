# 日文字幕全链路验证（解析 / 编码 / 时序 / 实时 ASR 语种路由）
#
# 三类用例：
#   1) parser：直接调 server/subtitle_file.py，覆盖 UTF-8 / UTF-8-BOM / CP932 / EUC-JP
#      × SRT / VTT / ASS，含平假名/片假名/々/～/〜/①/「」/・/长音ー
#   2) http  ：把同样的原始字节 POST 到 /api/subtitle/parse，验证服务端读取路径
#   3) ws    ：把日语 wav 按 256ms 实时喂进 /ws/audio，验证「不再被中英流式模型音译」
#
# 运行：.venv\Scripts\python.exe tests\e2e\test_ja_subtitle.py [parser|http|ws|all]

import asyncio
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVER = os.path.join(ROOT, "server")
TMP = os.path.join(ROOT, "tests", "fixtures")
SUBS = os.path.join(TMP, "subs")
BASE = "http://127.0.0.1:8790"
sys.path.insert(0, SERVER)

import subtitle_file  # noqa: E402

KANA = re.compile(r"[\u3040-\u30ff]")
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = ""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("  " + detail if detail else ""), flush=True)


# ---------------- 样本 ----------------

JA_UTF8 = [
    "今日はとても良い天気ですね。",
    "コーヒーとケーキをください。",
    "カタカナ：アイウエオ・ヴ　ひらがな：あいうえお",
    "時々、東京～大阪の新幹線①号に乗ります。『々』も表示できる。",
]
JA_CP932 = [
    "おはようございます、いい天気ですね。",
    "「コーヒー」と「ケーキ」をください。",
    "カタカナ：ヴァイオリン・アイウエオ　長音：コーヒー",
    "時々、東京～大阪の新幹線①号。",
]
JA_EUC = [
    "おはようございます。",
    "「こんにちは」とカタカナの「ヴァイオリン」。",
    "波ダッシュ〜と同の字点々を確認します。",
]
ZH = ["这是一个中文字幕测试。", "第二行需要正常显示标点：「引号」、顿号。"]
EN = ["This is an English subtitle test.", "Second line: 100% rendered."]
KO = ["안녕하세요. 오늘 날씨가 좋네요.", "두 번째 줄입니다."]

TIMES = [(0.5, 2.0), (2.5, 4.0), (4.5, 6.0), (6.5, 9.0)]


def _ts(sec: float, sep: str, frac: int = 3) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    whole = int(s)
    if frac == 3:
        tail = f"{int(round((s - whole) * 1000)):03d}"
    else:
        tail = f"{int(round((s - whole) * 100)):02d}"
    return f"{int(h)}:{int(m):02d}:{whole:02d}{sep}{tail}"


def srt_text(lines):
    return "\n".join(
        f"{i}\n{_ts(s, ',')} --> {_ts(e, ',')}\n{line}\n"
        for i, (line, (s, e)) in enumerate(zip(lines, TIMES), 1))


def vtt_text(lines):
    body = "".join(f"{_ts(s, '.')} --> {_ts(e, '.')}\n{line}\n\n"
                   for line, (s, e) in zip(lines, TIMES))
    return "WEBVTT\n\n" + body


def ass_text(lines):
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize\nStyle: Default,Arial,20\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
            "MarginV, Effect, Text\n")
    body = "".join(
        f"Dialogue: 0,{_ts(s, '.', 2)},{_ts(e, '.', 2)},Default,,0,0,0,,{{\\an8}}{line}\n"
        for line, (s, e) in zip(lines, TIMES))
    return head + body


# (文件名, 期望文本行, 编码, 期望格式, 期望语言提示)
CASES = [
    ("ja_utf8.srt", JA_UTF8, "utf-8", "srt", "ja"),
    ("ja_utf8bom.vtt", JA_UTF8, "utf-8-sig", "vtt", "ja"),
    ("ja_cp932.srt", JA_CP932, "cp932", "srt", "ja"),
    ("ja_cp932.vtt", JA_CP932, "cp932", "vtt", "ja"),
    ("ja_eucjp.ass", JA_EUC, "euc_jp", "ass", "ja"),
    ("zh_utf8.srt", ZH, "utf-8", "srt", ""),
    ("en_utf8.vtt", EN, "utf-8", "vtt", ""),
    ("ko_utf8.srt", KO, "utf-8", "srt", "ko"),
]


def build_samples():
    os.makedirs(SUBS, exist_ok=True)
    fmt_fn = {"srt": srt_text, "vtt": vtt_text, "ass": ass_text}
    files = []
    for name, lines, enc, fmt, hint in CASES:
        raw = fmt_fn[fmt](lines).encode(enc)
        with open(os.path.join(SUBS, name), "wb") as f:
            f.write(raw)
        files.append((name, lines, raw, fmt, hint))
    return files


# ---------------- 1) 解析器直测 ----------------

def phase_parser(files):
    print("\n=== 1) 解析器直测（SRT/VTT/ASS × UTF-8/BOM/CP932/EUC-JP）===", flush=True)
    for name, lines, raw, fmt, hint in files:
        d = subtitle_file.parse_subtitles(raw, name)
        print(f"[{name}] format={d['format']} encoding={d['encoding']} "
              f"count={d['count']} lang_hint={d['lang_hint'] or '无'} duration={d['duration']}",
              flush=True)
        for c in d["cues"]:
            print(f"    {c['start']:>5.2f}-{c['end']:>5.2f}  {c['text']}", flush=True)
        got = [c["text"] for c in d["cues"]]
        n = len(lines)
        exp_end = TIMES[n - 1][1]
        mid_t = (TIMES[n - 2][0] + TIMES[n - 2][1]) / 2 if n >= 2 else None
        check(f"{name} 格式={fmt}", d["format"] == fmt, d["format"])
        check(f"{name} 条目数={n}", d["count"] == n, str(d["count"]))
        check(f"{name} 语言提示={hint or '无'}", d["lang_hint"] == hint, d["lang_hint"])
        check(f"{name} 文本逐条精确一致", got == lines,
              "" if got == lines else f"{got} != {lines}")
        check(f"{name} 首条起点 0.5s", abs(d["cues"][0]["start"] - 0.5) < 0.001,
              str(d["cues"][0]["start"]))
        check(f"{name} 末条终点 {exp_end}s", abs(d["duration"] - exp_end) < 0.001, str(d["duration"]))
        if mid_t is not None:
            mid = subtitle_file.cue_at(d["cues"], mid_t)
            check(f"{name} t={mid_t}s 命中第 {n - 1} 条",
                  len(mid) == 1 and mid[0]["text"] == lines[n - 2],
                  str([c["text"] for c in mid]))
        check(f"{name} t=9.5s 无字幕", subtitle_file.cue_at(d["cues"], 9.5) == [])
        check(f"{name} 编码识别正确", _enc_ok(name, d["encoding"]), d["encoding"])


def _enc_ok(name: str, enc: str) -> bool:
    """cp932 文件允许被识别成 shift_jis（cp932 是超集）；JIS X 0213 系编码不接受
    （会把「～」U+FF5E 改成「〜」U+301C，见 subtitle_file._ENC_NORMALIZE）。"""
    exp = next(c[2] for c in CASES if c[0] == name)
    if exp == "cp932":
        return enc in ("cp932", "shift_jis", "cp932_2000")
    return enc == exp


# ---------------- 2) HTTP 端到端 ----------------

def phase_http(files):
    print("\n=== 2) HTTP /api/subtitle/parse（服务端真实读取路径）===", flush=True)
    for name, lines, raw, fmt, hint in files:
        req = urllib.request.Request(
            f"{BASE}/api/subtitle/parse?name={urllib.parse.quote(name)}",
            data=raw, method="POST", headers={"Content-Type": "application/octet-stream"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            check(f"{name} HTTP 解析", False, repr(e))
            continue
        got = [c["text"] for c in d.get("cues") or []]
        ok = bool(d.get("ok")) and d.get("format") == fmt and got == lines
        check(f"{name} HTTP 解析+文本一致", ok,
              f"{d.get('format')}/{d.get('encoding')}/{d.get('count')}")


# ---------------- 3) 实时 ASR 语种路由 ----------------

def wav_to_pcm(path: str) -> bytes:
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    out = subprocess.run([ff, "-v", "error", "-i", path, "-f", "s16le",
                          "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True)
    return out.stdout


async def ws_run(pcm: bytes, lang: str | None = None) -> list[dict]:
    """lang 非空时带 ?lang=<lang>，走「显式指定」路径（跳过 2s 语种嗅探）。"""
    import websockets
    subs: list[dict] = []
    url = "ws://127.0.0.1:8790/ws/audio" + (f"?lang={lang}" if lang else "")
    t_start = time.time()
    async with websockets.connect(url, max_size=4 * 1024 * 1024) as ws:
        async def recv():
            try:
                async for msg in ws:
                    d = json.loads(msg)
                    if d.get("type") == "subtitle":
                        d["wall_s"] = round(time.time() - t_start, 2)
                        subs.append(d)
                        print(f"    [{d.get('asr') or 'whisper'}] {d.get('lang')} → "
                              f"{d.get('translated')}   原文={d.get('original')!r} "
                              f"latency={d.get('latency_ms')}ms 到达={d['wall_s']}s", flush=True)
            except Exception:
                pass

        task = asyncio.create_task(recv())
        chunk = 8192            # 4096 样本 = 256ms，与扩展 ScriptProcessor 一致
        for i in range(0, len(pcm), chunk):
            await ws.send(pcm[i:i + chunk])
            await asyncio.sleep(0.25)
        await asyncio.sleep(12)  # 等最后一个 2.5s 窗口出结果
        task.cancel()
    return subs


KANA = re.compile(r"[\u3040-\u30ff]")
HANGUL = re.compile(r"[\uac00-\ud7af]")
JUNK = re.compile(r"^[\s⁇?？*＊]+$")


def _degenerate(text: str) -> bool:
    core = [c for c in text if not c.isspace()]
    if not core:
        return False
    return sum(1 for c in core if c in "⁇?？*＊") / len(core) >= 0.2


def phase_ws():
    print("\n=== 3) /ws/audio 实时链路（自动嗅探 + 显式 ?lang=）===", flush=True)
    cases = [
        (os.path.join(TMP, "tts_ja.wav"), "日语·自动嗅探", "ja", None),
        (os.path.join(TMP, "tts_ja.wav"), "日语·显式?lang=ja", "ja", "ja"),
        (os.path.join(TMP, "tts_zh.wav"), "中文·自动嗅探", "zh", None),
        (os.path.join(TMP, "tts_ko.wav"), "韩语·自动嗅探", "ko", None),
        (os.path.join(TMP, "tts_ko.wav"), "韩语·显式?lang=ko", "ko", "ko"),
        (os.path.join(TMP, "speech.wav"), "英语·自动嗅探", "en", None),
    ]
    for wav, label, lang, hint in cases:
        if not os.path.exists(wav):
            check(label, False, f"缺素材 {wav}")
            continue
        print(f"-- {label}  {os.path.basename(wav)}", flush=True)
        t0 = time.time()
        subs = asyncio.run(ws_run(wav_to_pcm(wav), lang=hint))
        print(f"   共 {len(subs)} 条，耗时 {time.time() - t0:.1f}s", flush=True)
        check(f"{label} 有字幕产出", len(subs) > 0, str(len(subs)))
        if not subs:
            continue
        first = subs[0]
        print(f"   首条：latency={first.get('latency_ms')}ms 到达={first.get('wall_s')}s "
              f"asr={first.get('asr')}", flush=True)
        text = " ".join(s.get("original") or "" for s in subs)
        if lang == "ja":
            check(f"{label} 原文含日文假名（不再音译）", bool(KANA.search(text)), repr(text[:90]))
            check(f"{label} 走流式通道（asr=stream）",
                  any((s.get("asr") or "") == "stream" for s in subs),
                  str({s.get("asr") for s in subs}))
        elif lang == "zh":
            check(f"{label} 原文含中文", bool(re.search(r"[\u4e00-\u9fff]", text)), repr(text[:90]))
            check(f"{label} 仍走流式管道（低延迟）",
                  any((s.get("asr") or "") == "stream" for s in subs),
                  str({s.get("asr") for s in subs}))
        elif lang == "ko":
            check(f"{label} 原文含谚文", bool(HANGUL.search(text)), repr(text[:90]))
            check(f"{label} 走流式通道（asr=stream）",
                  any((s.get("asr") or "") == "stream" for s in subs),
                  str({s.get("asr") for s in subs}))
        else:
            check(f"{label} 仍走流式管道", any((s.get("asr") or "") == "stream" for s in subs),
                  str({s.get("asr") for s in subs}))
        # 首条延迟门槛：
        #   显式 ?lang= 无嗅探等待，流式应亚秒级 → <1000ms
        #   自动嗅探含「攒 2s 音频 + whisper 判语种」的固定成本（实测 1.4-2.0s 判定），
        #   首条 latency 仍应远低于旧 whisper 通道的 2.7-8.1s → 放宽到 <5000ms 只拦灾难性回归
        limit = 1000 if hint else 5000
        check(f"{label} 首条延迟 < {limit}ms",
              (first.get("latency_ms") or 10 ** 9) < limit, f"{first.get('latency_ms')}ms")
        bad = [s for s in subs if _degenerate(s.get("translated") or "")]
        check(f"{label} 无星号/问号退化解", not bad,
              repr([b.get("translated") for b in bad][:3]))


if __name__ == "__main__":
    phases = sys.argv[1] if len(sys.argv) > 1 else "all"
    files = build_samples()
    if phases in ("all", "parser"):
        phase_parser(files)
    if phases in ("all", "http"):
        phase_http(files)
    if phases in ("all", "ws"):
        phase_ws()
    print(f"\n=== 结果：PASS {len(PASS)} / FAIL {len(FAIL)} ===", flush=True)
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f, flush=True)
        sys.exit(1)
