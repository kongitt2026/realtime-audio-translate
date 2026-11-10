# 命令行入口：python -m offline_translate "文本" / --file / --check
from __future__ import annotations

import argparse
import json
import sys

from .core import Translator


def _read_input(args) -> str:
    if args.text and args.text != "-":
        return args.text
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            return f.read()
    data = sys.stdin.buffer.read()
    return data.decode("utf-8", errors="replace")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="offline_translate",
        description="中日韩英文本翻译（Google 免费端点优先，Argos 离线兜底）",
    )
    p.add_argument("text", nargs="?", help="待译文本；传 - 表示从标准输入读取")
    p.add_argument("-f", "--from", dest="src", default="auto", help="源语种（默认自动识别）")
    p.add_argument("-t", "--to", dest="target", default="zh-CN", help="目标语种（默认 zh-CN）")
    p.add_argument("--file", help="从 UTF-8 文本文件读取")
    p.add_argument("--engine", action="append", help="只用指定引擎，可重复（google/google_chrome/argos）")
    p.add_argument("--json", action="store_true", help="输出完整 JSON 结果")
    p.add_argument("--check", action="store_true", help="只打印引擎链与离线语种")
    p.add_argument("--timeout", type=float, default=3.0)
    args = p.parse_args(argv)

    if args.engine:
        from .engines import ArgosOffline, GoogleChrome, GoogleGTX
        pool = {"google": GoogleGTX, "google_chrome": GoogleChrome, "argos": ArgosOffline}
        unknown = [n for n in args.engine if n not in pool]
        if unknown:
            print(f"未知引擎: {unknown}", file=sys.stderr)
            return 2
        engines = [pool[n](timeout=args.timeout) if n != "argos" else pool[n]() for n in args.engine]
        tr = Translator(target=args.target, engines=engines)
    else:
        tr = Translator(target=args.target, timeout=args.timeout)

    if args.check:
        print(json.dumps(tr.health(), ensure_ascii=False, indent=2))
        return 0

    text = _read_input(args)
    result = tr.translate(text, args.target)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result["translated"])
    return 1 if result.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
