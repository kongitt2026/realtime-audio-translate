# 让 `python -m offline_translate` 可直接运行
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
