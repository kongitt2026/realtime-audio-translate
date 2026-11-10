# 语言识别：Unicode 区间法（中日韩英），零依赖、零成本
# 优先级：假名 > 谚文 > 汉字 > 拉丁。纯汉字日语句子会被判成中文（已知取舍）。


def detect_lang(text: str) -> str:
    """返回 zh/ja/ko/en/other。"""
    if not text:
        return "other"
    hk = hg = hz = lt = 0
    for ch in text:
        cp = ord(ch)
        if 0x3040 <= cp <= 0x309F or 0x30A0 <= cp <= 0x30FF:
            hk += 1
        elif 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF:
            hg += 1
        elif 0x4E00 <= cp <= 0x9FFF:
            hz += 1
        elif (0x41 <= cp <= 0x5A) or (0x61 <= cp <= 0x7A):
            lt += 1
    if hk:
        return "ja"
    if hg:
        return "ko"
    if hz:
        return "zh"
    if lt:
        return "en"
    return "other"


# 目标语种别名 → 各引擎可接受的目标码
_TARGET_ALIASES = {
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
    "zh-tw": "zh-TW",
    "en": "en",
    "ja": "ja",
    "ko": "ko",
}


def normalize_target(target: str) -> str:
    return _TARGET_ALIASES.get((target or "zh-CN").lower(), target or "zh-CN")


# Argos 用两位小写码
def argos_code(target: str) -> str:
    return normalize_target(target).split("-")[0].lower()
