"""对账引擎：把原始记录分桶（全部确定性规则，无模型参与）。

分桶（每条记录恰好落入一个桶，按以下优先级判定）：
1. missing_uid       —— 未识别到有效 UID
2. duplicate_in_batch—— 本表内 UID+订单号 重复（保留第一条）
3. already_settled   —— 台账中该 UID（+订单号）已结算
4. manual_review     —— 金额缺失/无法解析，或状态列含异常关键词
5. amount_mismatch   —— 与台账参考金额差异超过容差
6. to_settle         —— 本次应结算
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from .excel_io import cell_to_text
from .money import parse_amount, round_amount
from .normalize import normalize_uid

TO_SETTLE = "to_settle"
ALREADY_SETTLED = "already_settled"
DUPLICATE_IN_BATCH = "duplicate_in_batch"
MISSING_UID = "missing_uid"
AMOUNT_MISMATCH = "amount_mismatch"
MANUAL_REVIEW = "manual_review"

BUCKET_ORDER = [TO_SETTLE, ALREADY_SETTLED, DUPLICATE_IN_BATCH,
                MISSING_UID, AMOUNT_MISMATCH, MANUAL_REVIEW]
BUCKET_LABELS = {
    TO_SETTLE: "待结算",
    ALREADY_SETTLED: "已结算跳过",
    DUPLICATE_IN_BATCH: "批内重复",
    MISSING_UID: "缺UID",
    AMOUNT_MISMATCH: "金额不一致",
    MANUAL_REVIEW: "需人工复核",
}


@dataclass
class RecItem:
    row_no: int
    bucket: str
    reason: str
    uid: Optional[str] = None
    raw_uid: str = ""
    order_no: Optional[str] = None
    amount: Optional[str] = None       # 舍入后的结算金额（字符串，保精度）
    raw_amount: str = ""
    ref_amount: Optional[str] = None   # 台账参考金额（金额不一致时填）
    date: str = ""
    name: str = ""


@dataclass
class ReconcileResult:
    batch_id: str
    source_file: str
    file_sha256: str
    generated_at: str
    mapping: dict
    summary: dict = field(default_factory=dict)
    items: list = field(default_factory=list)

    def bucket_items(self, bucket: str) -> list:
        return [i for i in self.items if i.bucket == bucket]

    def to_report(self) -> dict:
        return {
            "version": 1,
            "batch_id": self.batch_id,
            "source_file": self.source_file,
            "file_sha256": self.file_sha256,
            "generated_at": self.generated_at,
            "mapping": self.mapping,
            "summary": self.summary,
            "buckets": {b: [asdict(i) for i in self.bucket_items(b)]
                        for b in BUCKET_ORDER},
        }


def reconcile(records: list, ledger, config, *,
              source_file: str, file_sha256: str,
              now: Optional[datetime] = None) -> ReconcileResult:
    """核心对账。records 由 excel_io.apply_mapping 产出。"""
    now = now or datetime.now()
    batch_id = f"{now:%Y%m%d}-{file_sha256[:8]}"
    tolerance = config.tolerance
    prefixes = config.uid_prefixes
    uid_regex = config.uid_regex
    anomaly_keywords = config.anomaly_keywords

    items: list = []
    seen: dict = {}   # (uid, order_no) -> 首次出现的行号

    for rec in records:
        raw_uid = cell_to_text(rec.get("uid"))
        raw_amount = cell_to_text(rec.get("amount"))
        order_raw = cell_to_text(rec.get("order_no"))
        order_no = order_raw or None
        status_raw = cell_to_text(rec.get("status"))
        item = RecItem(
            row_no=rec["row_no"], bucket=TO_SETTLE, reason="本次应结算",
            raw_uid=raw_uid, order_no=order_no,
            raw_amount=raw_amount,
            date=cell_to_text(rec.get("date")),
            name=cell_to_text(rec.get("name")),
        )

        uid = normalize_uid(rec.get("uid"), prefixes=prefixes, uid_regex=uid_regex)
        amount = parse_amount(rec.get("amount"))
        item.uid = uid
        if amount is not None:
            item.amount = str(round_amount(amount, config.places, config.rounding))

        # 1. 缺 UID
        if not uid:
            item.bucket, item.reason = MISSING_UID, "未识别到有效 UID，需人工补充"
            items.append(item)
            continue

        # 2. 批内重复（UID+订单号）
        key = (uid, order_no or "")
        if key in seen:
            item.bucket = DUPLICATE_IN_BATCH
            item.reason = f"与本表第 {seen[key]} 行 UID+订单重复，只结算第一笔"
            items.append(item)
            continue
        seen[key] = item.row_no

        # 3. 台账已结算
        if ledger.is_settled(uid, order_no):
            item.bucket = ALREADY_SETTLED
            item.reason = "台账中该 UID（订单）已结算，本次不重复付"
            items.append(item)
            continue

        # 4. 金额无法解析 / 状态异常 -> 人工复核
        if amount is None:
            item.bucket = MANUAL_REVIEW
            item.reason = f"金额缺失或无法解析：「{raw_amount or '空'}」"
            items.append(item)
            continue
        hit = next((kw for kw in anomaly_keywords if kw in status_raw), None)
        if hit:
            item.bucket = MANUAL_REVIEW
            item.reason = f"状态列标记为「{status_raw}」，含关键词「{hit}」，需人工确认"
            items.append(item)
            continue

        # 5. 金额与台账参考值比对
        ref = ledger.reference_amount(uid, order_no)
        if ref is not None:
            ref_rounded = round_amount(ref, config.places, config.rounding)
            item.ref_amount = str(ref_rounded)
            if abs(round_amount(amount, config.places, config.rounding)
                   - ref_rounded) > tolerance:
                item.bucket = AMOUNT_MISMATCH
                item.reason = (f"本表金额 {item.amount} ≠ 台账参考金额 "
                               f"{item.ref_amount}（容差 {tolerance}）")
                items.append(item)
                continue

        # 6. 应结算
        items.append(item)

    to_settle_items = [i for i in items if i.bucket == TO_SETTLE]
    total = sum((Decimal(i.amount) for i in to_settle_items), Decimal(0))
    summary = {
        "total_rows": len(items),
        TO_SETTLE: len(to_settle_items),
        "to_settle_amount": str(round_amount(total, config.places, config.rounding)),
        ALREADY_SETTLED: sum(1 for i in items if i.bucket == ALREADY_SETTLED),
        DUPLICATE_IN_BATCH: sum(1 for i in items if i.bucket == DUPLICATE_IN_BATCH),
        MISSING_UID: sum(1 for i in items if i.bucket == MISSING_UID),
        AMOUNT_MISMATCH: sum(1 for i in items if i.bucket == AMOUNT_MISMATCH),
        MANUAL_REVIEW: sum(1 for i in items if i.bucket == MANUAL_REVIEW),
    }
    return ReconcileResult(
        batch_id=batch_id, source_file=source_file, file_sha256=file_sha256,
        generated_at=now.isoformat(timespec="seconds"),
        mapping=config.mapping or {}, summary=summary, items=items,
    )
