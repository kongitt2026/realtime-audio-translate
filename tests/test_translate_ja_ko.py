# 日/韩 → 中文翻译质量与格式验证（走已启动服务的 HTTP 接口，端到端）
# 用法：先启动服务（启动.bat），再运行
#   .venv\Scripts\python.exe tests\test_translate_ja_ko.py
# 验什么：语种识别、译文关键词命中、数字保真、编码（UTF-8 原始字节）、特殊字符/换行、异常入参
import json
import sys

import httpx

BASE = "http://127.0.0.1:8790"

# (编号, 原文, 期望语种, 必须出现的候选关键词[任一命中即算对], 必须保留的数字)
CASES = [
    ("J1", "今日はとても良い天気ですね。", "ja", ["天气"], ""),
    ("J2", "会議は午後3時から始まります。", "ja", ["会议"], "3"),
    ("J3", "この資料を100部コピーしてください。", "ja", ["复印", "复制", "拷贝"], "100"),
    ("J4", "東京から大阪まで新幹線で約2時間30分かかります。", "ja", ["新干线", "大阪"], "230"),
    ("J5", "ご不明な点がございましたら、お気軽にお問い合わせください。", "ja", ["咨询", "联系", "询问", "不明"], ""),
    ("J6", "AI技術は急速に発展しています。", "ja", ["AI", "人工智能"], ""),
    ("J7", "「重要」※注意：50%OFF！\n次行のテキストです。", "ja", ["重要"], "50"),
    ("K1", "오늘 날씨가 정말 좋네요.", "ko", ["天气"], ""),
    ("K2", "회의는 오후 3시에 시작합니다.", "ko", ["会议"], "3"),
    ("K3", "이 문서를 100부 복사해 주세요.", "ko", ["复印", "复制", "拷贝"], "100"),
    ("K4", "서울에서 부산까지 KTX로 약 2시간 30분 걸립니다.", "ko", ["釜山", "首尔", "KTX"], "230"),
    ("K5", "궁금한 점이 있으시면 언제든지 문의해 주세요.", "ko", ["咨询", "联系", "询问", "疑问"], ""),
    ("K6", "AI 기술은 빠르게 발전하고 있습니다.", "ko", ["AI", "人工智能"], ""),
    ("K7", "「중요」※주의: 50% 할인!\n다음 줄입니다.", "ko", ["重要"], "50"),
]


def post_text(client, text):
    r = client.post(f"{BASE}/api/translate", json={"text": text})
    return r, json.loads(r.content.decode("utf-8"))


def check_encoding(r, data):
    """原始字节必须是合法 UTF-8，且不能出现替换符/HTML 实体/转义残留。"""
    problems = []
    raw = r.content
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ["响应字节不是合法 UTF-8"]
    for field in ("original", "translated"):
        v = data.get(field, "")
        if "\ufffd" in v:
            problems.append(f"{field} 含替换符 U+FFFD（乱码）")
        if "&#" in v:
            problems.append(f"{field} 含 HTML 实体")
    return problems


def main():
    try:
        eng = json.loads(httpx.get(f"{BASE}/api/engines", timeout=15).content.decode("utf-8"))
    except Exception as e:
        print(f"[FATAL] 服务未启动或不可达：{e}")
        return 2
    print(f"[0] 引擎链 {eng['chain']}｜目标 {eng['target']}｜离线可译语种 {eng['offline_langs']}")
    if not eng.get("argos_ready") or not {"ja", "ko"} <= set(eng["offline_langs"]):
        print("     警告：Argos 离线 ja/ko 不可用（兜底会失效）")

    passed = failed = 0
    errors = []
    rows = []
    with httpx.Client(timeout=20) as client:
        for cid, src, want_lang, keys, digits in CASES:
            r, data = post_text(client, src)
            problems = []
            if r.status_code != 200:
                problems.append(f"HTTP {r.status_code}")
            problems += check_encoding(r, data)
            if data.get("original") != src:
                problems.append("original 未原样回显")
            if data.get("lang") != want_lang:
                problems.append(f"语种判定 {data.get('lang')} ≠ {want_lang}")
            out = data.get("translated") or ""
            if not out or out == src:
                problems.append("未产出译文")
            if not any(k in out for k in keys):
                problems.append(f"关键词未命中 {keys}")
            if digits and not all(d in out for d in digits):
                problems.append(f"数字丢失（需含 {digits}）")
            if "\n" in src and "\n" not in out:
                problems.append("换行未保留")
            ok = not problems
            passed += ok
            failed += not ok
            rows.append((cid, data.get("lang"), data.get("engine") or ("cache" if data.get("cached") else "-"), out.replace("\n", "\\n"), problems))
            if problems:
                errors.append((cid, problems))

        # 边界：中文原样跳过 / 空白 400
        _, zh = post_text(client, "这是一段中文，不应翻译。")
        if not (zh.get("skipped") and zh.get("translated") == "这是一段中文，不应翻译。"):
            errors.append(("E1", ["中文未按预期跳过"]))
            failed += 1
        else:
            passed += 1
            rows.append(("E1", "zh", "-", zh["translated"], []))
        r_blank = client.post(f"{BASE}/api/translate", json={"text": "   "})
        if r_blank.status_code != 400:
            errors.append(("E2", [f"空白入参未返回 400（实际 {r_blank.status_code}）"]))
            failed += 1
        else:
            passed += 1
            rows.append(("E2", "-", "-", "400 OK", []))

    print("\n[1] 逐条结果")
    for cid, lang, engine, out, problems in rows:
        mark = "PASS" if not problems else "FAIL"
        print(f"    {cid:3} {mark} lang={lang:<4} engine={(engine or '-'):<13} {out}")
        for p in problems:
            print(f"         ↳ {p}")

    print(f"\n[2] 汇总：{passed} 通过 / {failed} 失败（共 {len(rows)} 项）")
    if errors:
        print("[3] 问题清单：")
        for cid, problems in errors:
            print(f"    {cid}: {'；'.join(problems)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
