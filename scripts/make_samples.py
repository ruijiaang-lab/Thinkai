#!/usr/bin/env python3
"""生成示例 Excel（等价于 python3 -m scs.samples 的手动入口）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scs.samples import main  # noqa: E402

if __name__ == "__main__":
    main()
