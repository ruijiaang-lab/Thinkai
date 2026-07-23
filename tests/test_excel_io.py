from scs.excel_io import (apply_mapping, cell_to_text, detect_header_row,
                          guess_mapping)
from scs.samples import build_raw_workbook
from scs.excel_io import read_rows


def test_detect_header_row_skips_titles():
    rows = [
        ["供应链结算日报"],
        ["说明"],
        ["UID", "昵称", "订单号", "结算金额", "日期", "状态"],
        ["10001", "小七", "ORD-1", 10, "2026-07-22", "正常"],
    ]
    assert detect_header_row(rows) == 2


def test_detect_header_row_requires_two_fields():
    rows = [["备注", "随便"], ["a", "b"]]
    assert detect_header_row(rows) is None


def test_guess_mapping_on_sample(tmp_path):
    path = build_raw_workbook(tmp_path / "raw.xlsx")
    rows = read_rows(path)
    header_idx = detect_header_row(rows)
    assert header_idx == 2  # 第 3 行
    mapping = guess_mapping(rows, header_idx)
    assert mapping["uid"]["column"] == 0
    assert mapping["amount"]["column"] == 3
    assert mapping["order_no"]["column"] == 2
    assert mapping["status"]["column"] == 5


def test_apply_mapping_row_numbers_and_skip_empty(tmp_path):
    path = build_raw_workbook(tmp_path / "raw.xlsx")
    rows = read_rows(path)
    header_idx = detect_header_row(rows)
    mapping = guess_mapping(rows, header_idx)
    records = apply_mapping(rows, header_idx, mapping)
    assert len(records) == 12                    # 12 行数据
    assert records[0]["row_no"] == 4             # 表头第3行 -> 数据从第4行开始
    assert cell_to_text(records[0]["uid"]) == "10001"
    assert records[5]["uid"] is None             # 缺 UID 行


def test_apply_mapping_string_shortcut(tmp_path):
    path = build_raw_workbook(tmp_path / "raw.xlsx")
    rows = read_rows(path)
    header_idx = detect_header_row(rows)
    mapping = {"uid": "UID", "amount": "结算金额"}   # 手写简写格式
    records = apply_mapping(rows, header_idx, mapping)
    assert cell_to_text(records[0]["uid"]) == "10001"
    assert records[0]["amount"] == 120.0
