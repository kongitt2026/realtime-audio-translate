# 字幕文件解析：SRT / WebVTT / ASS-SSA + 日文常见编码自动检测
#
# 为什么要自己做：
#   项目 venv 里没有 srt / pysubs2 / webvtt（实测均未安装），且日文字幕大量是
#   Shift_JIS(CP932) / EUC-JP —— 直接按 UTF-8 读会抛 UnicodeDecodeError 或变成
#   乱码，这是「日文字幕显示不出来」的第二类根因（第一类是 ASR 语种，见
#   browser_audio.LangRoutePipeline）。
#
# 编码判定策略（确定性、可测）：
#   1) BOM 优先（UTF-8-BOM / UTF-16）
#   2) 严格 UTF-8 能解就直接用（覆盖率最高的快路径）
#   3) 其余候选（cp932/shift_jis/euc_jp/gb18030/big5/cp949）严格解码后打分：
#      全角假名×3 + 汉字/谚文×1 - 乱码字符×4，取最高分
#      （半宽片假名只算 0.5：EUC-JP 字节被误当 cp932 解时正好退化成半宽假名）
#   4) 全都失败 → UTF-8 replace 兜底，保证不崩

import codecs
import html
import re

__all__ = ["SubtitleParseError", "detect_and_decode", "guess_format",
           "parse_subtitles", "cue_at"]


class SubtitleParseError(ValueError):
    """字幕内容为空或格式无法识别。"""


_BOMS = [
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
]
_CANDIDATES = ["utf-8", "cp932", "shift_jis", "euc_jp", "gb18030", "big5", "cp949", "utf-16"]

# charset_normalizer 常把 CP932/EUC-JP 判成 JIS X 0213 系列（shift_jis_2004 /
# euc_jis_2004）。这类编码把「〜」(U+301C) 优先于 CP932 的「～」(U+FF5E) 映射，
# 会让原本正确的 CP932 字幕里波浪线/双 hyphen 等字符悄默改形（实测：
# 「東京～大阪」被解成「東京〜大阪」）。日文字幕领域 CP932 是事实标准，
# 因此把 2004/x0213 系列统一归一到各自的基线编码，保证字节往返一致。
_ENC_NORMALIZE = {
    "shift_jis_2004": "cp932",
    "shift_jisx0213": "cp932",
    "euc_jis_2004": "euc_jp",
    "euc_jisx0213": "euc_jp",
}

_KANA = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")
_HALF_KANA = re.compile(r"[\uff66-\uff9f]")
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]")
# 典型 mojibake 片段（UTF-8 被当 Latin-1 解、或 CJK 被当西文解）
_MOJIBAKE = re.compile(r"[\u00c0-\u00ff]{2,}|[\u0152\u0153\u0160\u0161\u0178\u017d\u017e"
                       r"\u0192\u02c6\u02dc\u2018\u2019\u201c\u201d\u2013\u2014\u2020"
                       r"\u2021\u2026\u2030\u2039\u203a\u20ac\u2122]")


def _score(text: str) -> float:
    return (len(_KANA.findall(text)) * 3.0
            + len(_HALF_KANA.findall(text)) * 0.5
            + len(_CJK.findall(text))
            - len(_MOJIBAKE.findall(text)) * 4.0)


def detect_and_decode(raw: bytes) -> tuple[str, str]:
    """返回 (encoding, text)。encoding 为实际采用的 Python codec 名。"""
    if not raw:
        raise SubtitleParseError("字幕内容为空")
    for bom, enc in _BOMS:
        if raw.startswith(bom):
            return enc, raw.decode(enc, errors="replace").lstrip("\ufeff")

    candidates = list(_CANDIDATES)
    try:                      # charset_normalizer 的猜测参与同一套打分，只作加分项
        from charset_normalizer import from_bytes
        best_guess = from_bytes(raw).best()
        if best_guess is not None and best_guess.encoding:
            enc = best_guess.encoding.lower().replace("-", "_")
            enc = _ENC_NORMALIZE.get(enc, enc)
            if enc not in candidates:
                candidates.insert(0, enc)
    except Exception:
        pass

    best: tuple[float, str, str] | None = None
    for enc in candidates:
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        if not text.strip():
            continue
        if enc.replace("_", "-").lower() in ("utf-8", "utf8"):
            # 严格 UTF-8 能解就是它：其它 CJK 编码几乎不可能恰好构成合法 UTF-8
            return "utf-8", text.lstrip("\ufeff")
        s = _score(text)
        if best is None or s > best[0]:
            best = (s, enc, text)
    if best is None:
        return "utf-8", raw.decode("utf-8", errors="replace")
    return best[1], best[2].lstrip("\ufeff")


_TS = re.compile(r"(?:(\d{1,3}):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})")
_CUE_TIME = re.compile(r"((?:\d{1,3}:)?\d{1,2}:\d{1,2}[.,]\d{1,3})\s*-->\s*"
                       r"((?:\d{1,3}:)?\d{1,2}:\d{1,2}[.,]\d{1,3})")
_TAG = re.compile(r"</?(?:i|b|u|s|em|strong|font|ruby|rt|rp|c|v|lang)\b[^>]*>", re.I)
_ASS_OVERRIDE = re.compile(r"\{[^}]*\}")


def _ts_to_sec(ts: str) -> float:
    m = _TS.search(ts)
    if not m:
        raise SubtitleParseError(f"无法解析时间戳: {ts!r}")
    h, mi, s, frac = m.groups()
    return (int(h or 0) * 3600 + int(mi) * 60 + int(s)
            + int(frac.ljust(3, "0")) / 1000.0)


def _clean_text(text: str) -> str:
    text = _TAG.sub("", text)
    text = html.unescape(text)
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n")]
    return "\n".join(ln for ln in lines if ln)


def guess_format(text: str, name: str = "") -> str:
    low = text.lstrip("\ufeff").lstrip()
    if re.search(r"^\[(script info|events|v4\+? styles)\]", low, re.I | re.M):
        return "ass"
    if low[:6].upper().startswith("WEBVTT"):
        return "vtt"
    suffix = (name or "").lower().rsplit(".", 1)[-1] if "." in (name or "") else ""
    if suffix in ("ass", "ssa"):
        return "ass"
    if suffix == "vtt":
        return "vtt"
    return "srt"


def _parse_cue_blocks(text: str) -> list[dict]:
    """SRT 与 WebVTT 共用：以空行分块，块内找 `-->` 行，其后都是正文。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cues: list[dict] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        head = lines[0].strip().upper()
        if head.startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if idx is None:
            continue
        m = _CUE_TIME.search(lines[idx])
        if not m:
            continue
        body = _clean_text("\n".join(lines[idx + 1:]))
        if not body:
            continue
        cues.append({"start": round(_ts_to_sec(m.group(1)), 3),
                     "end": round(_ts_to_sec(m.group(2)), 3),
                     "text": body})
    return cues


def _parse_ass(text: str) -> list[dict]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    fields = None
    cues: list[dict] = []
    section = ""
    default_fields = ["layer", "start", "end", "style", "name",
                      "marginl", "marginr", "marginv", "effect", "text"]
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1].strip().lower()
            continue
        if section != "events":
            continue
        low = s.lower()
        if low.startswith("format:"):
            fields = [f.strip().lower() for f in s.split(":", 1)[1].split(",")]
            continue
        if not low.startswith("dialogue:"):
            continue
        fields = fields or default_fields
        parts = s.split(":", 1)[1].split(",", len(fields) - 1)
        row = dict(zip(fields, parts))
        try:
            start = _ts_to_sec(row.get("start", ""))
            end = _ts_to_sec(row.get("end", ""))
        except SubtitleParseError:
            continue
        body = _ASS_OVERRIDE.sub("", row.get("text", ""))
        body = body.replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", " ")
        body = _clean_text(body)
        if not body:
            continue
        cues.append({"start": round(start, 3), "end": round(end, 3), "text": body})
    return cues


def _lang_hint(text: str) -> str:
    ja = len(_KANA.findall(text))
    ko = len(re.findall(r"[\uac00-\ud7af\u1100-\u11ff]", text))
    if ja and ja >= ko:
        return "ja"
    if ko:
        return "ko"
    return ""


def parse_subtitles(raw: bytes, name: str = "") -> dict:
    """原始字节 → {format, encoding, cues, count, lang_hint, duration}。"""
    encoding, text = detect_and_decode(raw)
    fmt = guess_format(text, name)
    cues = _parse_ass(text) if fmt == "ass" else _parse_cue_blocks(text)
    if not cues:
        raise SubtitleParseError(f"未解析到任何字幕条目（格式 {fmt}，编码 {encoding}）")
    cues.sort(key=lambda c: c["start"])
    return {
        "format": fmt,
        "encoding": encoding,
        "cues": cues,
        "count": len(cues),
        "lang_hint": _lang_hint("\n".join(c["text"] for c in cues)),
        "duration": round(max(c["end"] for c in cues), 3),
    }


def cue_at(cues: list[dict], t: float) -> list[dict]:
    """取时刻 t 上正在显示的字幕（可能重叠多条），供时序校验/前端复用。"""
    return [c for c in cues if c["start"] <= t < c["end"]]
