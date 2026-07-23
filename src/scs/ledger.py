"""结算台账：SQLite 单一事实来源 + 已处理文件登记表（幂等）。"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .money import parse_amount, round_amount

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    uid         TEXT NOT NULL,
    order_no    TEXT,
    amount      TEXT NOT NULL,
    status      TEXT NOT NULL,          -- settled / pending / quote
    batch_id    TEXT,
    source_file TEXT,
    note        TEXT DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entries_uid ON entries(uid);
CREATE TABLE IF NOT EXISTS processed_files (
    sha256       TEXT PRIMARY KEY,
    filename     TEXT NOT NULL,
    batch_id     TEXT,
    processed_at TEXT NOT NULL
);
"""


class Ledger:
    def __init__(self, db_path, readonly: bool = False):
        self.db_path = Path(db_path)
        self.conn: Optional[sqlite3.Connection] = None
        if readonly and not self.db_path.exists():
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    # ---- 已处理文件（幂等控制）----
    def file_processed(self, sha256: str) -> Optional[dict]:
        if not self.conn:
            return None
        row = self.conn.execute(
            "SELECT * FROM processed_files WHERE sha256=?", (sha256,)
        ).fetchone()
        return dict(row) if row else None

    def mark_file_processed(self, sha256: str, filename: str, batch_id: str,
                            processed_at: Optional[str] = None):
        assert self.conn
        self.conn.execute(
            "INSERT OR IGNORE INTO processed_files(sha256, filename, batch_id, processed_at)"
            " VALUES(?,?,?,?)",
            (sha256, filename, batch_id,
             processed_at or datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    # ---- 结算状态查询（精确匹配）----
    def is_settled(self, uid: str, order_no: Optional[str] = None) -> bool:
        if not self.conn:
            return False
        sql = "SELECT 1 FROM entries WHERE uid=? AND status='settled'"
        args: list = [uid]
        if order_no:
            sql += " AND (order_no=? OR order_no IS NULL OR order_no='')"
            args.append(order_no)
        return self.conn.execute(sql, args).fetchone() is not None

    def reference_amount(self, uid: str,
                         order_no: Optional[str] = None) -> Optional[Decimal]:
        """取该 UID 最近一条 pending/quote 参考金额（用于金额比对）。"""
        if not self.conn:
            return None
        sql = ("SELECT amount FROM entries WHERE uid=? AND status IN ('pending','quote')")
        args: list = [uid]
        if order_no:
            sql += " AND (order_no=? OR order_no IS NULL OR order_no='')"
            args.append(order_no)
        sql += " ORDER BY id DESC LIMIT 1"
        row = self.conn.execute(sql, args).fetchone()
        if not row:
            return None
        return parse_amount(row["amount"])

    # ---- 写入 ----
    def add_entry(self, uid: str, order_no: Optional[str], amount: Decimal,
                  status: str, batch_id: str, source_file: str = "",
                  note: str = "", ts: Optional[str] = None):
        assert self.conn
        amt = str(round_amount(amount, 2, "half_up"))
        self.conn.execute(
            "INSERT INTO entries(uid, order_no, amount, status, batch_id,"
            " source_file, note, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (uid, order_no or "", amt, status, batch_id, source_file, note,
             ts or datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def add_settlements(self, items: list, batch_id: str, source_file: str,
                        settled_at: str) -> int:
        """把对账结果里的待结算条目写入台账（status=settled）。"""
        assert self.conn
        n = 0
        for it in items:
            amount = parse_amount(it.get("amount"))
            uid = (it.get("uid") or "").strip()
            if amount is None or not uid:
                continue
            self.add_entry(uid, it.get("order_no"), amount, "settled",
                           batch_id, source_file, ts=settled_at)
            n += 1
        return n

    # ---- 查询与统计 ----
    def query(self, uid: Optional[str] = None, limit: int = 50) -> list:
        if not self.conn:
            return []
        if uid:
            rows = self.conn.execute(
                "SELECT * FROM entries WHERE uid=? ORDER BY id DESC LIMIT ?",
                (uid, limit)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM entries ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        if not self.conn:
            return {"entries": 0, "settled": 0, "settled_amount": "0.00",
                    "processed_files": 0}
        total = self.conn.execute("SELECT COUNT(*) c FROM entries").fetchone()["c"]
        settled_rows = self.conn.execute(
            "SELECT amount FROM entries WHERE status='settled'").fetchall()
        settled_sum = sum((parse_amount(r["amount"]) or Decimal(0)
                           for r in settled_rows), Decimal(0))
        files = self.conn.execute(
            "SELECT COUNT(*) c FROM processed_files").fetchone()["c"]
        return {
            "entries": total,
            "settled": len(settled_rows),
            "settled_amount": str(round_amount(settled_sum, 2, "half_up")),
            "processed_files": files,
        }
