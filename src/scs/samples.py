"""示例数据生成器（确定性，无随机）。

raw 表故意覆盖所有对账场景：
- 普通应结算 / 带空格 UID / 浮点 UID / 全角 UID / 带前缀 UID / 金额需舍入
- 批内重复、缺 UID、已结算、金额不一致、金额无法解析、状态异常
history 表提供：两条已结算 + 一条待定报价（供金额比对）。
"""
from __future__ import annotations

from pathlib import Path

import openpyxl


def build_raw_workbook(path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "每日结算原始表"
    ws.append(["供应链结算日报 2026-07-23"])          # 第1行：标题（测试表头识别）
    ws.append(["说明：本表由供应链群每日发送"])        # 第2行：备注
    ws.append(["UID", "昵称", "订单号", "结算金额", "日期", "状态"])  # 第3行：表头
    rows = [
        ["10001", "小七", "ORD-9001", 120.00, "2026-07-22", "正常"],        # 应结算
        [" 10002 ", "阿明", "ORD-9002", 88.50, "2026-07-22", "正常"],       # 空格 UID -> 应结算
        [10002.0, "阿明", "ORD-9003", 45.00, "2026-07-22", "正常"],         # 浮点 UID -> 应结算
        ["Ｕ10086", "大壮", "ORD-9004", 200.00, "2026-07-22", "正常"],      # 全角 -> 应结算
        ["10001", "小七", "ORD-9001", 120.00, "2026-07-22", "正常"],        # 批内重复
        [None, "无名", "ORD-9006", 30.00, "2026-07-22", "正常"],            # 缺 UID
        ["20001", "老王", "ORD-8001", 300.00, "2026-07-22", "正常"],        # 台账已结算
        ["10003", "莉莉", "ORD-9007", 58.00, "2026-07-22", "正常"],         # 金额不一致(台账参考50)
        ["10004", "强子", "ORD-9008", "待定", "2026-07-22", "正常"],        # 金额无法解析
        ["10005", "小芳", "ORD-9009", 66.60, "2026-07-22", "异常-退款"],    # 状态异常
        ["UID:10006", "老赵", "ORD-9010", 99.90, "2026-07-22", "正常"],     # 前缀 UID -> 应结算
        ["10007", "孙姐", "ORD-9011", 1234.567, "2026-07-22", "正常"],      # 金额舍入 1234.57
    ]
    for r in rows:
        ws.append(r)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def build_history_workbook(path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "历史结算台账"
    ws.append(["UID", "订单号", "金额", "状态", "结算日期"])
    rows = [
        [20001, "ORD-8001", 300.00, "已结算", "2026-07-15"],
        [20002, "ORD-8002", 150.00, "已结算", "2026-07-16"],
        [10003, "ORD-9007", 50.00, "待定", ""],      # 报价参考 -> 触发金额不一致
    ]
    for r in rows:
        ws.append(r)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def main():
    root = Path(__file__).resolve().parents[2]
    samples = root / "samples"
    p1 = build_raw_workbook(samples / "raw_2026-07-23.xlsx")
    p2 = build_history_workbook(samples / "history_ledger.xlsx")
    print(f"✓ 已生成示例原始表：{p1}")
    print(f"✓ 已生成示例历史台账：{p2}")


if __name__ == "__main__":
    main()
