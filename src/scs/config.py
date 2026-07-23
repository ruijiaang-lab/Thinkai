"""工作区布局与配置管理。"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

# 默认配置：所有规则显式可调，不靠猜
DEFAULTS = {
    "version": 1,
    "amount_places": 2,              # 金额小数位
    "rounding": "half_up",           # 舍入模式：half_up（四舍五入）/ half_even（银行家舍入）
    "amount_tolerance": "0.01",      # 金额比对容差
    "uid_prefixes": ["UID:", "UID", "用户", "账号"],  # 标准化时要剥离的前缀
    "uid_regex": None,               # 可选：UID 合法格式正则（None = 不校验格式）
    "mapping": None,                 # 字段映射：{"uid": {"column": 0, "header": "UID"}, ...}
    "anomaly_status_keywords": ["异常", "退款", "冻结", "暂停", "退单", "作废", "冲红"],
}


def default_workspace() -> Path:
    """默认工作区：环境变量 SCS_WORKSPACE 优先，否则用插件根目录下的 workspace/。"""
    env = os.environ.get("SCS_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    # src/scs/config.py -> 上三级 = 插件根目录
    return Path(__file__).resolve().parents[2] / "workspace"


class Workspace:
    """工作区目录结构（本地文件夹收件箱模式）。"""

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.inbox = self.root / "settlement-inbox"   # 放原始 Excel
        self.ledger_dir = self.root / "ledger"        # SQLite 台账
        self.ledger_db = self.ledger_dir / "settlement.db"
        self.output = self.root / "output"            # 结算预览 + 报告
        self.archive = self.root / "archive"          # 已处理文件归档
        self.audit_file = self.root / "audit" / "audit.jsonl"  # 审计日志
        self.config_file = self.root / "config.json"

    def ensure(self) -> None:
        for d in (self.root, self.inbox, self.ledger_dir, self.output,
                  self.archive, self.audit_file.parent):
            d.mkdir(parents=True, exist_ok=True)

    def describe(self) -> dict:
        return {
            "工作区": str(self.root),
            "收件箱": str(self.inbox),
            "台账": str(self.ledger_db),
            "输出": str(self.output),
            "归档": str(self.archive),
            "审计日志": str(self.audit_file),
        }


class Config:
    """config.json 的读写封装。缺省项自动补齐。"""

    def __init__(self, workspace_root: Path, data: dict):
        self.path = Path(workspace_root) / "config.json"
        self.data = {**DEFAULTS, **data}

    @classmethod
    def load(cls, workspace_root: Path) -> "Config":
        path = Path(workspace_root) / "config.json"
        data = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        return cls(workspace_root, data)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    # ---- 常用取值 ----
    @property
    def mapping(self) -> dict | None:
        return self.data.get("mapping")

    def set_mapping(self, mapping: dict) -> None:
        self.data["mapping"] = mapping

    @property
    def uid_prefixes(self) -> list:
        return list(self.data.get("uid_prefixes") or [])

    @property
    def uid_regex(self):
        return self.data.get("uid_regex")

    @property
    def places(self) -> int:
        return int(self.data.get("amount_places", 2))

    @property
    def rounding(self) -> str:
        return str(self.data.get("rounding", "half_up"))

    @property
    def tolerance(self) -> Decimal:
        return Decimal(str(self.data.get("amount_tolerance", "0.01")))

    @property
    def anomaly_keywords(self) -> list:
        return list(self.data.get("anomaly_status_keywords") or [])
