"""UID / 状态的确定性标准化。

规则全部显式、可复现，绝不依赖模型推断：
1. 数字型（Excel 常把 UID 存成 10002.0）转整数字符串；
2. NFKC 归一化（全角 -> 半角，如 Ｕ１００８６ -> U10086）；
3. 去除所有空白字符；
4. 转大写；
5. 剥离可配置前缀（如 "UID:"）与前导分隔符；
6. 可选正则校验。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

STATUS_MAP = {
    "已结算": "settled", "settled": "settled", "完成": "settled", "已付": "settled",
    "待定": "pending", "pending": "pending", "未结算": "pending",
    "报价": "quote", "quote": "quote",
}


def normalize_uid(
    raw,
    *,
    prefixes: Optional[list] = None,
    uid_regex: Optional[str] = None,
) -> Optional[str]:
    """把任意来源的 UID 原始值标准化成唯一可比对形式；无法识别返回 None。"""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, float):
        if raw.is_integer():
            s = str(int(raw))
        else:
            s = repr(raw)
    elif isinstance(raw, int):
        s = str(raw)
    else:
        s = str(raw)

    s = s.strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return None

    s = unicodedata.normalize("NFKC", s)   # 全角 -> 半角
    s = "".join(s.split())                 # 去掉所有空白
    s = s.upper()

    for p in (prefixes or []):
        p = str(p).upper().strip()
        if p and s.startswith(p):
            s = s[len(p):]
            break
    s = s.lstrip(":：-—_ ")               # 剥前缀后残留的分隔符
    if not s:
        return None

    if uid_regex and not re.fullmatch(uid_regex, s):
        return None
    return s


def normalize_status(raw, default: str = "settled") -> str:
    """台账状态标准化为 settled / pending / quote。"""
    if raw is None:
        return default
    s = unicodedata.normalize("NFKC", str(raw)).strip().lower()
    return STATUS_MAP.get(s, default)
