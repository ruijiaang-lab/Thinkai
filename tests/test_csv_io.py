"""CSV 支持测试：编码探测（UTF-8 BOM / GBK）、表头识别、完整 CLI 流程。

真实场景：抖音/微信等平台导出的结算数据几乎都是 CSV，且常带 BOM、
字段内前导制表符（防科学计数法）。
"""
import json

from conftest import run_scs
from scs.excel_io import detect_header_row, guess_mapping, read_rows


def _write_csv(path, text, encoding="utf-8-sig"):
    path.write_bytes(text.encode(encoding))
    return path


DOUYIN_STYLE = "\n".join([
    "主订单编号,子订单编号,选购商品,订单应付金额,达人ID,达人昵称,订单状态,售后状态",
    '"\t9001","\t9001",玉肌皂,29.90,"\t7592255573464597541",黄飞,已发货,-',
    '"\t9002","\t9002",玉肌皂,49.90,"\t7592255573464597541",黄飞,已发货,-',
    '"\t9003","\t9003",玉肌皂,29.90,"\t7592255573464597541",黄飞,已关闭,退款成功',
])


def test_read_csv_utf8_bom(tmp_path):
    p = _write_csv(tmp_path / "a.csv", DOUYIN_STYLE)
    rows = read_rows(p)
    assert rows[0][0] == "主订单编号"          # BOM 已被剥掉
    assert rows[1][0] == "\t9001"              # 前导制表符原样保留（交给标准化环节）
    assert rows[1][3] == "29.90"
    assert len(rows) == 4


def test_read_csv_gbk(tmp_path):
    text = "UID,金额\n10001,88.50\n10002,99.00\n"
    p = _write_csv(tmp_path / "gbk.csv", text, encoding="gbk")
    rows = read_rows(p)
    assert rows[0] == ["UID", "金额"]
    assert rows[1][0] == "10001"


def test_header_and_mapping_on_csv(tmp_path):
    rows = read_rows(_write_csv(tmp_path / "a.csv", DOUYIN_STYLE))
    idx = detect_header_row(rows)
    assert idx == 0
    mapping = guess_mapping(rows, idx)
    assert mapping["amount"]["header"] == "订单应付金额"
    assert mapping["status"]["header"] == "订单状态"
    assert mapping["name"]["header"] == "达人昵称"


def test_csv_full_cli_flow(tmp_path, scs_bin):
    """CSV 走完整 CLI：scan 识别 → 映射 → reconcile 分桶 → apply 幂等。"""
    ws = tmp_path / "workspace"
    csv_file = _write_csv(tmp_path / "raw.csv", DOUYIN_STYLE)
    (ws / "settlement-inbox").mkdir(parents=True)
    import shutil
    inbox = ws / "settlement-inbox" / "raw.csv"
    shutil.copy(csv_file, inbox)

    # scan 认得 csv
    p = run_scs(scs_bin, "scan", "--json", workspace=ws)
    files = json.loads(p.stdout)["files"]
    assert len(files) == 1 and files[0]["format"] == ".csv"
    assert files[0]["processed"] is False and "sha256" in files[0]

    # 映射（含 order_no，避免同 UID 被当批内重复）
    run_scs(scs_bin, "save-mapping", "--mapping",
            '{"uid":"达人ID","amount":"订单应付金额","order_no":"子订单编号","status":"订单状态"}',
            workspace=ws)

    # 业务规则："已关闭"订单不应结算——加进异常关键词（config.json 显式可调）
    cfg_path = ws / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["anomaly_status_keywords"].append("已关闭")
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    # reconcile：前导制表符 UID 能被标准化；已发货 2 笔待结算，已关闭 1 笔转人工复核
    p = run_scs(scs_bin, "reconcile", str(inbox), "--json", workspace=ws)
    rep = json.loads(p.stdout)
    s = rep["summary"]
    assert s["to_settle"] == 2
    assert s["to_settle_amount"] == "79.80"      # 29.90 + 49.90
    assert s["duplicate_in_batch"] == 0
    assert s["manual_review"] == 1               # 已关闭那笔
    # UID 标准化：前导制表符已剥掉
    uids = {i["uid"] for i in rep["buckets"]["to_settle"]}
    assert uids == {"7592255573464597541"}

    # apply + 幂等
    report = rep["output"]["report_json"]
    p = run_scs(scs_bin, "apply", report, "--yes", "--json", workspace=ws)
    assert json.loads(p.stdout)["settled_count"] == 2
    p = run_scs(scs_bin, "apply", report, "--yes", workspace=ws, expect_fail=True)
    assert "已结算过" in p.stderr


def test_xls_still_rejected(tmp_path, scs_bin):
    f = tmp_path / "old.xls"
    f.write_bytes(b"\xd0\xcf\x11\xe0")
    p = run_scs(scs_bin, "reconcile", str(f), workspace=tmp_path / "ws",
                expect_fail=True)
    assert ".xlsx / .csv" in p.stderr
