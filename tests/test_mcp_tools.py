"""MCP 服务器工具函数直测（不走协议层，纯函数级）。

每个 scs_* 工具都是对 CLI 处理器的转发，覆盖完整对账流程：
init → 导台账 → scan → 映射 → reconcile → apply（含未确认拒绝、幂等、force）→ 查台账 → 审计。
"""
import shutil

import server  # mcp/server.py（conftest 已把 mcp/ 加入 sys.path）
from scs.samples import build_history_workbook, build_raw_workbook

IMPORT_MAPPING = {"uid": "UID", "order_no": "订单号", "amount": "金额", "status": "状态"}


def _setup(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    monkeypatch.setenv("SCS_WORKSPACE", str(ws))
    raw = build_raw_workbook(tmp_path / "raw.xlsx")
    history = build_history_workbook(tmp_path / "history.xlsx")
    return ws, raw, history


def test_tool_list_registered():
    """11 个工具全部注册到 FastMCP，且名字符合 scs_ 前缀约定。"""
    names = {fn.__name__ for fn in server.TOOLS}
    assert names == {
        "scs_init", "scs_status", "scs_scan", "scs_guess_mapping",
        "scs_save_mapping", "scs_show_mapping", "scs_reconcile", "scs_apply",
        "scs_import_ledger", "scs_query_ledger", "scs_audit_log",
    }


def test_init_and_status(tmp_path, monkeypatch):
    ws, _, _ = _setup(tmp_path, monkeypatch)
    r = server.scs_init()
    assert r["ok"] is True
    assert (ws / "settlement-inbox").is_dir()
    assert (ws / "config.json").is_file()

    s = server.scs_status()
    assert s["mapping_ready"] is False
    assert s["inbox_total"] == 0


def test_full_tool_flow(tmp_path, monkeypatch):
    ws, raw, history = _setup(tmp_path, monkeypatch)
    server.scs_init()

    # 导入历史台账
    r = server.scs_import_ledger(str(history), IMPORT_MAPPING)
    assert r["imported"] == 3

    # 原始表进收件箱 → scan
    inbox_file = ws / "settlement-inbox" / "raw.xlsx"
    shutil.copy(raw, inbox_file)
    r = server.scs_scan()
    assert len(r["files"]) == 1
    assert r["files"][0]["processed"] is False

    # 字段映射：识别 → 保存 → 查看
    g = server.scs_guess_mapping(str(inbox_file))
    assert "uid" in g["mapping"] and "amount" in g["mapping"]
    r = server.scs_save_mapping(file=str(inbox_file))
    assert r["ok"] is True
    assert server.scs_show_mapping()["mapping"]

    # 对账：桶计数与金额核对（与 CLI E2E 同一组断言）
    rep = server.scs_reconcile(str(inbox_file))
    s = rep["summary"]
    assert s["total_rows"] == 12
    assert s["to_settle"] == 6
    assert s["to_settle_amount"] == "1787.97"
    assert s["already_settled"] == 1
    assert s["duplicate_in_batch"] == 1
    assert s["missing_uid"] == 1
    assert s["amount_mismatch"] == 1
    assert s["manual_review"] == 2
    report_path = rep["output"]["report_json"]

    # apply 未确认 → 拒绝（工具级强制）
    r = server.scs_apply(report_path)
    assert r["ok"] is False
    assert "确认" in r["error"]

    # apply 确认 → 写入台账
    r = server.scs_apply(report_path, confirmed=True)
    assert r["ok"] is True
    assert r["settled_count"] == 6
    assert r["settled_amount"] == "1787.97"

    # 查台账：UID 有记录
    r = server.scs_query_ledger(uid="10001")
    assert r["entries"]

    # 幂等：同一报告再 apply → 拒绝
    r = server.scs_apply(report_path, confirmed=True)
    assert r["ok"] is False
    assert "已结算过" in r["error"]

    # force 重跑 → 允许（纠错场景）
    r = server.scs_apply(report_path, confirmed=True, force=True)
    assert r["ok"] is True

    # 审计日志含 apply 留痕
    a = server.scs_audit_log(limit=30)
    actions = [e.get("action") for e in a["entries"]]
    assert "apply_settlement" in actions


def test_manual_mapping_and_errors(tmp_path, monkeypatch):
    ws, raw, _ = _setup(tmp_path, monkeypatch)
    server.scs_init()

    # 手动 mapping（dict 参数）保存
    r = server.scs_save_mapping(mapping={"uid": "UID", "amount": "结算金额"})
    assert r["ok"] is True

    # 文件不存在 → 结构化错误，不抛异常
    r = server.scs_reconcile(str(tmp_path / "不存在.xlsx"))
    assert r["ok"] is False
    assert "不存在" in r["error"]

    # save_mapping 两个参数都不给 → 结构化错误
    r = server.scs_save_mapping()
    assert r["ok"] is False
