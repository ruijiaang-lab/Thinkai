"""命令行入口：scs —— 供应链结算对账工具。

所有金额/匹配/去重/写台账均由确定性程序完成；
--json 输出结构化结果，供 Codex 等 AI 助手直接解析。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from . import __version__, audit
from .config import Config, Workspace, default_workspace
from .engine import BUCKET_LABELS, BUCKET_ORDER, TO_SETTLE, reconcile
from .excel_io import (apply_mapping, detect_header_row, guess_mapping,
                       mapping_summary, read_rows)
from .idempotency import sha256_file
from .ledger import Ledger
from .money import parse_amount, round_amount
from .normalize import normalize_status, normalize_uid
from .report import write_preview_excel


class ScsError(Exception):
    """面向用户的错误（中文提示，退出码 2）。"""


def _print_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _money(x) -> str:
    return f"¥{x}"


# ---------------------------------------------------------------- init
def cmd_init(args, ws: Workspace) -> int:
    ws.ensure()
    cfg_path = ws.config_file
    existed = cfg_path.exists()
    cfg = Config.load(ws.root)
    if not existed:
        cfg.save()
    audit.append(ws.audit_file, "init", workspace=str(ws.root))
    if args.json:
        _print_json({"ok": True, "workspace": str(ws.root),
                     "created_config": not existed, **ws.describe()})
        return 0
    print(f"✓ 工作区已就绪：{ws.root}")
    for k, v in ws.describe().items():
        print(f"  {k}：{v}")
    if not existed:
        print("  已生成默认配置 config.json（映射、容差、舍入规则可在其中调整）")
    return 0


# ---------------------------------------------------------------- scan
def cmd_scan(args, ws: Workspace) -> int:
    ws.ensure()
    files = sorted(
        f for f in ws.inbox.iterdir()
        if f.is_file() and not f.name.startswith("~$")
        and f.suffix.lower() in {".xlsx", ".xls"}
    ) if ws.inbox.exists() else []
    ledger = Ledger(ws.ledger_db, readonly=True)
    out = []
    for f in files:
        info = {
            "name": f.name, "path": str(f),
            "format": f.suffix.lower(),
            "size_kb": round(f.stat().st_size / 1024, 1),
            "mtime": datetime.fromtimestamp(f.stat().st_mtime)
                             .strftime("%Y-%m-%d %H:%M"),
        }
        if f.suffix.lower() == ".xlsx":
            sha = sha256_file(f)
            info["sha256"] = sha
            done = ledger.file_processed(sha)
            info["processed"] = bool(done)
            info["processed_batch"] = done["batch_id"] if done else None
        else:
            info["processed"] = False
            info["warning"] = "旧版 .xls 不支持，请先另存为 .xlsx"
        out.append(info)
    ledger.close()

    if args.json:
        _print_json({"workspace": str(ws.root), "inbox": str(ws.inbox),
                     "files": out})
        return 0

    if not out:
        print(f"收件箱是空的：{ws.inbox}")
        print("把供应链群发的 .xlsx 放进这个目录，再运行 scan。")
        return 0
    print(f"收件箱（{ws.inbox}）共 {len(out)} 个文件：")
    for i in out:
        if i.get("warning"):
            print(f"  ⚠ {i['name']}（{i['mtime']}）—— {i['warning']}")
            continue
        status = "已处理" if i["processed"] else "待处理"
        mark = "✓" if i["processed"] else "•"
        extra = f"（批次 {i['processed_batch']}）" if i["processed"] else ""
        print(f"  {mark} {i['name']}  {i['size_kb']}KB  {i['mtime']}  [{status}]{extra}")
    pending = [i for i in out if not i["processed"] and i["format"] == ".xlsx"]
    if pending:
        print(f"\n待处理 {len(pending)} 个。下一步：scs reconcile <文件>")
    return 0


# ------------------------------------------------------- guess / save mapping
def _load_sheet(path: Path):
    rows = read_rows(path)
    header_idx = detect_header_row(rows)
    if header_idx is None:
        raise ScsError(f"没能从 {path.name} 认出表头（前 15 行里找不到"
                       f"含 UID/金额等字段的行）。请用 save-mapping --json 手动指定列名。")
    return rows, header_idx


def cmd_guess_mapping(args, ws: Workspace) -> int:
    path = Path(args.file).expanduser().resolve()
    rows, header_idx = _load_sheet(path)
    mapping = guess_mapping(rows, header_idx)
    if args.json:
        _print_json({"file": str(path), "header_row": header_idx + 1,
                     "mapping": mapping})
        return 0
    print(f"文件：{path.name}（表头在第 {header_idx + 1} 行）")
    print("字段识别建议：")
    print(mapping_summary(mapping))
    print("\n确认无误后运行：scs save-mapping --file " + str(path))
    return 0


def cmd_save_mapping(args, ws: Workspace) -> int:
    ws.ensure()
    if args.mapping:
        try:
            mapping = json.loads(args.mapping)
        except json.JSONDecodeError as e:
            raise ScsError(f"--mapping 解析失败：{e}")
        if not isinstance(mapping, dict):
            raise ScsError("--mapping 需要是对象，如 {\"uid\":\"UID\",\"amount\":\"金额\"}")
    elif args.file:
        path = Path(args.file).expanduser().resolve()
        rows, header_idx = _load_sheet(path)
        mapping = guess_mapping(rows, header_idx)
    else:
        raise ScsError("请提供 --file <Excel> 或 --mapping '<映射JSON>'")

    if "uid" not in mapping or "amount" not in mapping:
        raise ScsError("映射必须包含 uid 和 amount 两个字段。\n"
                       + mapping_summary(mapping))
    cfg = Config.load(ws.root)
    cfg.set_mapping(mapping)
    cfg.save()
    audit.append(ws.audit_file, "mapping_saved", mapping=mapping)
    if args.json:
        _print_json({"ok": True, "mapping": mapping})
        return 0
    print("✓ 字段映射已保存到 config.json：")
    print(mapping_summary(mapping))
    return 0


def cmd_show_mapping(args, ws: Workspace) -> int:
    cfg = Config.load(ws.root)
    if args.json:
        _print_json({"mapping": cfg.mapping})
        return 0
    if not cfg.mapping:
        print("还没有保存字段映射。先运行：scs guess-mapping <文件>")
        return 0
    print("当前字段映射：")
    print(mapping_summary(cfg.mapping))
    return 0


# ------------------------------------------------------------- reconcile
def cmd_reconcile(args, ws: Workspace) -> int:
    ws.ensure()
    path = Path(args.file).expanduser().resolve()
    if not path.exists():
        raise ScsError(f"文件不存在：{path}")
    if path.suffix.lower() != ".xlsx":
        raise ScsError(f"暂只支持 .xlsx 格式（收到：{path.name}）。"
                       f"如为旧版 .xls，请先用 Excel/WPS 另存为 .xlsx。")

    cfg = Config.load(ws.root)
    if args.mapping_json:
        try:
            cfg.data["mapping"] = json.loads(args.mapping_json)
        except json.JSONDecodeError as e:
            raise ScsError(f"--mapping-json 解析失败：{e}")
    if not cfg.mapping:
        raise ScsError("还没配置字段映射。先运行：scs guess-mapping <文件>，"
                       "确认后 scs save-mapping --file <文件>")

    rows, header_idx = _load_sheet(path)
    records = apply_mapping(rows, header_idx, cfg.mapping)
    if not records:
        raise ScsError(f"{path.name} 表头下方没有数据行。")

    sha = sha256_file(path)
    ledger = Ledger(ws.ledger_db)
    already = ledger.file_processed(sha)

    result = reconcile(records, ledger, cfg, source_file=str(path),
                       file_sha256=sha)
    report_path = ws.output / f"报告_{result.batch_id}.json"
    preview_path = ws.output / f"结算预览_{result.batch_id}.xlsx"
    report_path.write_text(
        json.dumps(result.to_report(), ensure_ascii=False, indent=2),
        encoding="utf-8")
    write_preview_excel(result, preview_path)
    audit.append(ws.audit_file, "reconcile_preview", batch_id=result.batch_id,
                 file=path.name, sha256=sha, summary=result.summary)
    ledger.close()

    if args.json:
        out = result.to_report()
        out["output"] = {"preview_xlsx": str(preview_path),
                         "report_json": str(report_path)}
        out["already_processed"] = bool(already)
        _print_json(out)
        return 0

    s = result.summary
    print(f"═══ 对账完成 批次 {result.batch_id} ═══")
    if already:
        print(f"⚠ 该文件之前已处理过（批次 {already['batch_id']}），"
              f"apply 会被拒绝，除非加 --force。")
    print(f"源文件：{path.name}（共 {s['total_rows']} 行数据）")
    print(f"  ● 待结算      {s[TO_SETTLE]:>4} 笔   金额 {_money(s['to_settle_amount'])}")
    for b in BUCKET_ORDER[1:]:
        if s[b]:
            print(f"  · {BUCKET_LABELS[b]:<8} {s[b]:>4} 笔")
    print(f"\n预览表：{preview_path}")
    print(f"报告：  {report_path}")
    print("\n人工检查预览表后，运行：scs apply " + str(report_path) + " --yes")
    return 0


# ---------------------------------------------------------------- apply
def cmd_apply(args, ws: Workspace) -> int:
    ws.ensure()
    if not args.yes:
        raise ScsError("写入台账是不可撤销操作，必须由人确认后加 --yes 执行。")
    report_path = Path(args.report).expanduser().resolve()
    if not report_path.exists():
        raise ScsError(f"报告不存在：{report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for key in ("batch_id", "file_sha256", "buckets", "summary"):
        if key not in report:
            raise ScsError(f"报告缺少字段 {key}，不是本工具生成的对账报告。")

    sha = report["file_sha256"]
    batch_id = report["batch_id"]
    ledger = Ledger(ws.ledger_db)
    done = ledger.file_processed(sha)
    if done and not args.force:
        raise ScsError(f"该文件已结算过（批次 {done['batch_id']}，"
                       f"时间 {done['processed_at']}）。为防止重复结算已拒绝；"
                       f"确认要重跑请加 --force。")

    to_settle = report["buckets"].get(TO_SETTLE, [])
    settled_at = datetime.now().isoformat(timespec="seconds")
    n = ledger.add_settlements(to_settle, batch_id, report.get("source_file", ""),
                               settled_at)
    ledger.mark_file_processed(sha, Path(report.get("source_file", "")).name,
                               batch_id, settled_at)

    archived = None
    src = Path(report.get("source_file", ""))
    if src.exists():
        day = datetime.now().strftime("%Y%m%d")
        dst = ws.archive / f"{day}_{src.name}"
        shutil.move(str(src), str(dst))
        archived = str(dst)

    amount = report["summary"].get("to_settle_amount", "0.00")
    audit.append(ws.audit_file, "apply_settlement", batch_id=batch_id,
                 sha256=sha, settled_count=n, settled_amount=amount,
                 archived=archived, operator="cli")
    stats = ledger.stats()
    ledger.close()

    if args.json:
        _print_json({"ok": True, "batch_id": batch_id, "settled_count": n,
                     "settled_amount": amount, "archived": archived,
                     "ledger": stats})
        return 0
    print(f"✓ 批次 {batch_id} 已写入台账：{n} 笔，合计 {_money(amount)}")
    if archived:
        print(f"  源文件已归档：{archived}")
    print(f"  台账当前：{stats['settled']} 笔已结算，累计 {_money(stats['settled_amount'])}")
    return 0


# ---------------------------------------------------------- import-ledger
def cmd_import_ledger(args, ws: Workspace) -> int:
    ws.ensure()
    if not args.mapping:
        raise ScsError('import-ledger 需要 --mapping 指定列名映射，例如：\n'
                       '  --mapping \'{"uid":"UID","order_no":"订单号",'
                       '"amount":"金额","status":"状态"}\'')
    try:
        mapping = json.loads(args.mapping)
    except json.JSONDecodeError as e:
        raise ScsError(f"--mapping 解析失败：{e}")
    if "uid" not in mapping or "amount" not in mapping:
        raise ScsError("导入映射必须包含 uid 和 amount 列。")

    path = Path(args.file).expanduser().resolve()
    rows, header_idx = _load_sheet(path)
    records = apply_mapping(rows, header_idx, mapping)

    cfg = Config.load(ws.root)
    batch_id = f"import-{datetime.now():%Y%m%d%H%M%S}"
    ledger = Ledger(ws.ledger_db)
    imported, skipped = 0, 0
    for rec in records:
        uid = normalize_uid(rec.get("uid"), prefixes=cfg.uid_prefixes,
                            uid_regex=cfg.uid_regex)
        amount = parse_amount(rec.get("amount"))
        if not uid or amount is None:
            skipped += 1
            continue
        status = normalize_status(rec.get("status"), default=args.default_status)
        ledger.add_entry(uid, (str(rec.get("order_no")).strip()
                               if rec.get("order_no") is not None else None),
                         amount, status, batch_id, source_file=path.name)
        imported += 1
    audit.append(ws.audit_file, "ledger_imported", file=path.name,
                 batch_id=batch_id, imported=imported, skipped=skipped)
    ledger.close()

    if args.json:
        _print_json({"file": str(path), "batch_id": batch_id,
                     "imported": imported, "skipped": skipped})
        return 0
    print(f"✓ 从 {path.name} 导入台账：{imported} 条"
          + (f"，跳过 {skipped} 条（缺 UID 或金额无法解析）" if skipped else ""))
    print(f"  状态规则：已结算/完成 -> settled，待定/未结算 -> pending，"
          f"其余按 --default-status（默认 {args.default_status}）")
    return 0


# ---------------------------------------------------------------- ledger
def cmd_ledger(args, ws: Workspace) -> int:
    ledger = Ledger(ws.ledger_db, readonly=True)
    rows = ledger.query(uid=args.uid, limit=args.limit)
    stats = ledger.stats()
    ledger.close()
    if args.json:
        _print_json({"stats": stats, "entries": rows})
        return 0
    if args.uid:
        if not rows:
            print(f"台账中没有 UID = {args.uid} 的记录（未结算过）。")
        else:
            print(f"UID {args.uid} 的台账记录（最新 {len(rows)} 条）：")
            for r in rows:
                print(f"  [{r['status']}] 订单 {r['order_no'] or '-'}  "
                      f"{_money(r['amount'])}  批次 {r['batch_id']}  {r['created_at']}")
        return 0
    if not rows:
        print("台账为空。可用 import-ledger 导入历史结算表。")
        return 0
    print(f"台账最近 {len(rows)} 条记录：")
    for r in rows:
        print(f"  {r['uid']}  [{r['status']}]  订单 {r['order_no'] or '-'}  "
              f"{_money(r['amount'])}  {r['created_at']}")
    print(f"\n合计：{stats['settled']} 笔已结算，累计 {_money(stats['settled_amount'])}")
    return 0


# ----------------------------------------------------------------- audit
def cmd_audit(args, ws: Workspace) -> int:
    entries = audit.tail(ws.audit_file, limit=args.limit)
    if args.json:
        _print_json({"entries": entries})
        return 0
    if not entries:
        print("还没有操作记录。")
        return 0
    print(f"最近 {len(entries)} 条操作记录：")
    for e in entries:
        print("  " + audit.format_entry(e))
    return 0


# ---------------------------------------------------------------- status
def cmd_status(args, ws: Workspace) -> int:
    ws.ensure()
    ledger = Ledger(ws.ledger_db, readonly=True)
    stats = ledger.stats()
    inbox_files = [f for f in ws.inbox.iterdir()
                   if f.is_file() and not f.name.startswith("~$")
                   and f.suffix.lower() == ".xlsx"] if ws.inbox.exists() else []
    pending = [f for f in inbox_files if not ledger.file_processed(sha256_file(f))]
    ledger.close()
    cfg = Config.load(ws.root)
    info = {
        "workspace": str(ws.root),
        "mapping_ready": bool(cfg.mapping),
        "inbox_total": len(inbox_files),
        "inbox_pending": len(pending),
        "pending_files": [f.name for f in pending],
        **stats,
        "recent_audit": [audit.format_entry(e)
                         for e in audit.tail(ws.audit_file, 3)],
    }
    if args.json:
        _print_json(info)
        return 0
    print(f"工作区：{ws.root}")
    print(f"字段映射：{'已配置 ✓' if cfg.mapping else '未配置（先 guess-mapping）'}")
    print(f"收件箱：{info['inbox_total']} 个文件，待处理 {info['inbox_pending']} 个")
    for name in info["pending_files"]:
        print(f"  • {name}")
    print(f"台账：{stats['settled']} 笔已结算，累计 {_money(stats['settled_amount'])}；"
          f"已处理文件 {stats['processed_files']} 个")
    if info["recent_audit"]:
        print("最近操作：")
        for line in info["recent_audit"]:
            print(f"  {line}")
    return 0


# ------------------------------------------------------------------ main
HANDLERS = {
    "init": cmd_init,
    "scan": cmd_scan,
    "guess-mapping": cmd_guess_mapping,
    "save-mapping": cmd_save_mapping,
    "show-mapping": cmd_show_mapping,
    "reconcile": cmd_reconcile,
    "apply": cmd_apply,
    "import-ledger": cmd_import_ledger,
    "ledger": cmd_ledger,
    "audit": cmd_audit,
    "status": cmd_status,
}


def main(argv=None) -> int:
    # --json 放在子命令前后都可用：
    # 主解析器 default=False；子解析器用 SUPPRESS，只在显式传入时覆盖。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true",
                        default=argparse.SUPPRESS, help="输出结构化 JSON")

    parser = argparse.ArgumentParser(
        prog="scs",
        description="供应链结算对账工具 —— 金额/匹配/去重全部确定性计算")
    parser.add_argument("--version", action="version", version=f"scs {__version__}")
    parser.add_argument("--workspace", default=None,
                        help="工作区目录（默认：插件目录下 workspace/ 或 $SCS_WORKSPACE）")
    parser.add_argument("--json", action="store_true", default=False,
                        help="输出结构化 JSON")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", parents=[common],
                   help="初始化工作区（收件箱/台账/输出/归档/审计）")

    sub.add_parser("scan", parents=[common],
                   help="扫描收件箱里的 Excel，标记已处理/待处理")

    p = sub.add_parser("guess-mapping", parents=[common],
                       help="识别 Excel 表头，给出字段映射建议")
    p.add_argument("file")

    p = sub.add_parser("save-mapping", parents=[common],
                       help="保存字段映射到 config.json")
    p.add_argument("--file", help="从该 Excel 自动识别并保存")
    p.add_argument("--mapping", metavar="JSON",
                   help='手动指定，如 \'{"uid":"UID","amount":"金额"}\'')

    sub.add_parser("show-mapping", parents=[common], help="查看当前字段映射")

    p = sub.add_parser("reconcile", parents=[common],
                       help="对账并生成结算预览（不写台账）")
    p.add_argument("file")
    p.add_argument("--mapping-json", help="临时覆盖字段映射（不保存）")

    p = sub.add_parser("apply", parents=[common],
                       help="确认后把待结算写入台账（需 --yes）")
    p.add_argument("report", help="reconcile 生成的报告 JSON 路径")
    p.add_argument("--yes", action="store_true", help="人工确认标记")
    p.add_argument("--force", action="store_true", help="允许重跑已处理文件（慎用）")

    p = sub.add_parser("import-ledger", parents=[common],
                       help="导入历史结算 Excel 建台账")
    p.add_argument("file")
    p.add_argument("--mapping", required=False,
                   help='列名映射 JSON（必填），如 \'{"uid":"UID","amount":"金额"}\'')
    p.add_argument("--default-status", default="settled",
                   choices=["settled", "pending", "quote"])

    p = sub.add_parser("ledger", parents=[common], help="查询台账")
    p.add_argument("--uid", help="查指定 UID 是否已结算")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("audit", parents=[common], help="查看审计日志")
    p.add_argument("--limit", type=int, default=10)

    sub.add_parser("status", parents=[common], help="工作区总览")

    args = parser.parse_args(argv)
    ws_root = (Path(args.workspace).expanduser().resolve()
               if args.workspace else default_workspace())
    ws = Workspace(ws_root)
    try:
        return HANDLERS[args.cmd](args, ws)
    except ScsError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"✗ 文件不存在：{e.filename or e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
