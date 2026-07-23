"""金额的确定性解析与舍入（全程 Decimal，禁用 float 运算）。"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, ROUND_HALF_UP
from typing import Optional

_STRIP_RE = re.compile(r"[¥￥$€,，\s_]")
ROUNDINGS = {"half_up": ROUND_HALF_UP, "half_even": ROUND_HALF_EVEN}


def parse_amount(raw) -> Optional[Decimal]:
    """解析金额：支持数字、'1,234.50'、'¥88.5' 等；无法解析返回 None。"""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        try:
            return Decimal(str(raw))
        except InvalidOperation:
            return None
    s = unicodedata.normalize("NFKC", str(raw)).strip()
    if not s or s.lower() in {"nan", "none", "null", "-", "—"}:
        return None
    s = _STRIP_RE.sub("", s)
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def round_amount(d: Decimal, places: int = 2, mode: str = "half_up") -> Decimal:
    """按指定小数位与模式舍入。默认四舍五入（half_up），财务常用。"""
    quantum = Decimal(1).scaleb(-places)
    return d.quantize(quantum, rounding=ROUNDINGS.get(mode, ROUND_HALF_UP))
