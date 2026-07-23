"""审计日志：只追加（append-only）的 JSONL，任何写操作都留痕。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


def append(audit_file: Path, action: str, **detail) -> dict:
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        **detail,
    }
    audit_file = Path(audit_file)
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    return entry


def tail(audit_file: Path, limit: int = 10) -> list:
    audit_file = Path(audit_file)
    if not audit_file.exists():
        return []
    lines = audit_file.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for line in lines:
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"raw": line})
    return out


def format_entry(entry: dict) -> str:
    ts = entry.get("ts", "?")
    action = entry.get("action", "?")
    skip = {"ts", "action"}
    parts = [f"{k}={entry[k]}" for k in entry if k not in skip
             and not isinstance(entry[k], (dict, list))]
    return f"[{ts}] {action}" + (f"  {' '.join(parts)}" if parts else "")
