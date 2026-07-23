"""端到端测试：init -> 导入历史 -> scan -> 映射 -> reconcile -> apply -> 幂等拒绝。"""
import json
import shutil

from conftest import run_scs
from scs.samples import build_history_workbook, build_raw_workbook

IMPORT_MAPPING = ('{"uid":"UID","order_no":"订单号","amount":"金额","status":"状态"}')


def _setup(tmp_path):
    ws = tmp_path / "workspace"
    raw = build_raw_workbook(tmp_path / "raw_2026-07-23.xlsx")
    history = build_history_workbook(tmp_path / "history_ledger.xlsx")
    return ws, raw, history


def test_full_flow(tmp_path, scs_bin):
    ws, raw, history = _setup(tmp_path)

    # 1. 初始化
    p = run_scs(scs_bin, "init", workspace=ws)
    assert "工作区已就绪" in p.stdout
    assert (ws / "settlement-inbox").is_dir()
    assert (ws / "config.json").is_file()

    # 2. 原始表放进收件箱
    shutil.copy(raw, ws / "settlement-inbox" / raw.name)

    # 3. scan：应识别出 1 个待处理文件
    p = run_scs(scs_bin, "scan", "--json", workspace=ws)
    data = json.loads(p.stdout)
    assert len(data["files"]) == 1
    assert data["files"][0]["processed"] is False

    # 4. 字段识别与保存
    p = run_scs(scs_bin, "guess-mapping", str(ws / "settlement-inbox" / raw.name),
                "--json", workspace=ws)
    guessed = json.loads(p.stdout)["mapping"]
    assert "uid" in guessed and "amount" in guessed
    run_scs(scs_bin, "save-mapping", "--file",
            str(ws / "settlement-inbox" / raw.name), workspace=ws)

    # 5. 导入历史台账
    p = run_scs(scs_bin, "import-ledger", str(history),
                "--mapping", IMPORT_MAPPING, "--json", workspace=ws)
    imported = json.loads(p.stdout)
    assert imported["imported"] == 3

    # 6. 对账：核对各桶计数与金额
    p = run_scs(scs_bin, "reconcile",
                str(ws / "settlement-inbox" / raw.name), "--json", workspace=ws)
    report = json.loads(p.stdout)
    s = report["summary"]
    assert s["total_rows"] == 12
    assert s["to_settle"] == 6
    assert s["to_settle_amount"] == "1787.97"   # 120+88.5+45+200+99.9+1234.57
    assert s["already_settled"] == 1
    assert s["duplicate_in_batch"] == 1
    assert s["missing_uid"] == 1
    assert s["amount_mismatch"] == 1
    assert s["manual_review"] == 2

    # 金额不一致项应带台账参考值
    mm = report["buckets"]["amount_mismatch"][0]
    assert mm["ref_amount"] == "50.00"
    assert mm["uid"] == "10003"

    # 预览 Excel 与报告文件真实存在
    from pathlib import Path
    assert Path(report["output"]["preview_xlsx"]).is_file()
    report_path = report["output"]["report_json"]
    assert Path(report_path).is_file()

    # 7. apply 前未确认 -> 拒绝
    p = run_scs(scs_bin, "apply", report_path, workspace=ws, expect_fail=True)
    assert "--yes" in p.stderr

    # 8. 确认后写入台账
    p = run_scs(scs_bin, "apply", report_path, "--yes", workspace=ws)
    assert "已写入台账：6 笔" in p.stdout
    assert "¥1787.97" in p.stdout

    # 9. 台账可查到已结算；UID 查询可用
    p = run_scs(scs_bin, "ledger", "--uid", "10001", "--json", workspace=ws)
    entries = json.loads(p.stdout)["entries"]
    assert len(entries) == 1
    assert entries[0]["status"] == "settled"
    assert entries[0]["amount"] == "120.00"

    # 10. 审计日志有 apply 记录
    p = run_scs(scs_bin, "audit", "--json", workspace=ws)
    actions = [e["action"] for e in json.loads(p.stdout)["entries"]]
    assert "apply_settlement" in actions

    # 11. 源文件已归档，收件箱清空
    assert not (ws / "settlement-inbox" / raw.name).exists()
    archived = list((ws / "archive").glob("*.xlsx"))
    assert len(archived) == 1

    # 12. 幂等：同一文件再处理一遍，apply 必须被拒绝
    shutil.copy(raw, ws / "settlement-inbox" / raw.name)
    p = run_scs(scs_bin, "reconcile",
                str(ws / "settlement-inbox" / raw.name), "--json", workspace=ws)
    report2 = json.loads(p.stdout)
    assert report2["already_processed"] is True
    p = run_scs(scs_bin, "apply", report2["output"]["report_json"], "--yes",
                workspace=ws, expect_fail=True)
    assert "已结算过" in p.stderr or "已处理" in p.stderr

    # 台账没有被重复写入：仍是 6 笔（加上导入的 3 条历史 = entries 9 条，settled 8 笔）
    p = run_scs(scs_bin, "ledger", "--limit", "100", "--json", workspace=ws)
    data = json.loads(p.stdout)
    assert data["stats"]["settled"] == 8       # 历史 2 笔已结算 + 本次 6 笔
    assert data["stats"]["settled_amount"] == "2237.97"  # 300+150+1787.97

    # 13. status 总览可用：重复放进来的同文件被识别为"已处理"，不再 pending
    p = run_scs(scs_bin, "status", "--json", workspace=ws)
    st = json.loads(p.stdout)
    assert st["mapping_ready"] is True
    assert st["inbox_total"] == 1
    assert st["inbox_pending"] == 0


def test_reconcile_without_mapping_fails(tmp_path, scs_bin):
    ws, raw, _ = _setup(tmp_path)
    run_scs(scs_bin, "init", workspace=ws)
    p = run_scs(scs_bin, "reconcile", str(raw), workspace=ws, expect_fail=True)
    assert "字段映射" in p.stderr


def test_xls_rejected(tmp_path, scs_bin):
    ws, _, _ = _setup(tmp_path)
    run_scs(scs_bin, "init", workspace=ws)
    fake = tmp_path / "old.xls"
    fake.write_bytes(b"fake")
    p = run_scs(scs_bin, "reconcile", str(fake), workspace=ws, expect_fail=True)
    assert "xlsx" in p.stderr.lower()
