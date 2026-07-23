"""文件哈希：幂等控制的基础。同一个文件绝不允许被重复结算。"""
from __future__ import annotations

from pathlib import Path


def sha256_file(path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def short_hash(sha: str, n: int = 8) -> str:
    return Path(sha[:n]).name
