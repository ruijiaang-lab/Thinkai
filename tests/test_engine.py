from decimal import Decimal

import pytest

from scs.config import Config
from scs.engine import (ALREADY_SETTLED, AMOUNT_MISMATCH, DUPLICATE_IN_BATCH,
                        MANUAL_REVIEW, MISSING_UID, TO_SETTLE, reconcile)
from scs.ledger import Ledger


@pytest.fixture
def cfg(tmp_path):
    cfg = Config(tmp_path, {})
    cfg.data["mapping"] = {"uid": "UID", "amount": "金额"}
    return cfg


@pytest.fixture
def ledger(tmp_path):
    lg = Ledger(tmp_path / "ledger.db")
    yield lg
    lg.close()


def rec(row_no, uid, amount, order=None, status="正常", date="", name=""):
    return {"row_no": row_no, "uid": uid, "amount": amount,
            "order_no": order, "date": date, "name": name, "status": status}


def test_to_settle_basic(cfg, ledger):
    result = reconcile([rec(4, "10001", 120)], ledger, cfg,
                       source_file="a.xlsx", file_sha256="h" * 64)
    assert result.summary[TO_SETTLE] == 1
    assert result.summary["to_settle_amount"] == "120.00"
    assert result.items[0].uid == "10001"
    assert result.items[0].amount == "120.00"


def test_missing_uid(cfg, ledger):
    result = reconcile([rec(4, None, 30), rec(5, "  ", 30)], ledger, cfg,
                       source_file="a.xlsx", file_sha256="h" * 64)
    assert result.summary[MISSING_UID] == 2


def test_duplicate_in_batch_keeps_first(cfg, ledger):
    records = [rec(4, "10001", 120, order="O1"), rec(5, "10001", 120, order="O1")]
    result = reconcile(records, ledger, cfg,
                       source_file="a.xlsx", file_sha256="h" * 64)
    assert result.summary[TO_SETTLE] == 1
    assert result.summary[DUPLICATE_IN_BATCH] == 1
    dup = result.bucket_items(DUPLICATE_IN_BATCH)[0]
    assert "第 4 行" in dup.reason


def test_same_uid_different_order_not_duplicate(cfg, ledger):
    records = [rec(4, "10002", 10, order="O1"), rec(5, "10002", 20, order="O2")]
    result = reconcile(records, ledger, cfg,
                       source_file="a.xlsx", file_sha256="h" * 64)
    assert result.summary[TO_SETTLE] == 2


def test_already_settled(cfg, ledger):
    ledger.add_entry("20001", "ORD-8001", Decimal("300"), "settled", "b1", "old.xlsx")
    result = reconcile([rec(4, "20001", 300, order="ORD-8001")], ledger, cfg,
                       source_file="a.xlsx", file_sha256="h" * 64)
    assert result.summary[ALREADY_SETTLED] == 1
    assert result.summary[TO_SETTLE] == 0


def test_amount_mismatch_against_pending_reference(cfg, ledger):
    ledger.add_entry("10003", "ORD-9007", Decimal("50.00"), "pending", "b1", "old.xlsx")
    result = reconcile([rec(4, "10003", 58, order="ORD-9007")], ledger, cfg,
                       source_file="a.xlsx", file_sha256="h" * 64)
    assert result.summary[AMOUNT_MISMATCH] == 1
    item = result.bucket_items(AMOUNT_MISMATCH)[0]
    assert item.ref_amount == "50.00"


def test_amount_within_tolerance_ok(cfg, ledger):
    ledger.add_entry("10003", None, Decimal("50.00"), "pending", "b1", "old.xlsx")
    result = reconcile([rec(4, "10003", "50.005")], ledger, cfg,
                       source_file="a.xlsx", file_sha256="h" * 64)
    # 50.005 -> 50.01，与 50.00 差 0.01，不超过容差 0.01
    assert result.summary[TO_SETTLE] == 1


def test_unparseable_amount_manual_review(cfg, ledger):
    result = reconcile([rec(4, "10004", "待定")], ledger, cfg,
                       source_file="a.xlsx", file_sha256="h" * 64)
    assert result.summary[MANUAL_REVIEW] == 1


def test_anomaly_status_manual_review(cfg, ledger):
    result = reconcile([rec(4, "10005", 66.6, status="异常-退款")], ledger, cfg,
                       source_file="a.xlsx", file_sha256="h" * 64)
    assert result.summary[MANUAL_REVIEW] == 1


def test_amount_rounded_in_settlement(cfg, ledger):
    result = reconcile([rec(4, "10007", 1234.567)], ledger, cfg,
                       source_file="a.xlsx", file_sha256="h" * 64)
    item = result.bucket_items(TO_SETTLE)[0]
    assert item.amount == "1234.57"
    assert result.summary["to_settle_amount"] == "1234.57"


def test_batch_id_from_hash_and_date(cfg, ledger):
    from datetime import datetime
    now = datetime(2026, 7, 23, 10, 0)
    result = reconcile([rec(4, "1", 1)], ledger, cfg,
                       source_file="a.xlsx", file_sha256="abc12345" + "0" * 56,
                       now=now)
    assert result.batch_id == "20260723-abc12345"


def test_report_roundtrip_shape(cfg, ledger):
    result = reconcile([rec(4, "10001", 120)], ledger, cfg,
                       source_file="a.xlsx", file_sha256="h" * 64)
    report = result.to_report()
    assert set(report) >= {"version", "batch_id", "source_file", "file_sha256",
                           "generated_at", "mapping", "summary", "buckets"}
    assert len(report["buckets"][TO_SETTLE]) == 1
