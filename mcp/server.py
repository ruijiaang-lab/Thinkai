#!/usr/bin/env python3
"""Supply Chain Settlement MCP 服务器。

把确定性引擎（src/scs）以 MCP 工具形式暴露给 Claude Code / Codex 等 AI 助手。

铁律：金额、匹配、去重、舍入、写台账全部由 src/scs 的确定性程序完成；
本服务器只是 JSON-RPC 转发层（转发 bin/scs 同款处理器），自己绝不算一分钱。

运行：python3 mcp/server.py（stdio 传输）
工作区：$SCS_WORKSPACE 优先，否则 <插件根>/workspace/
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import types
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from scs import cli  # noqa: E402
from scs.config import Workspace, default_workspace  # noqa: E402

mcp = FastMCP("supply-chain-settlement")

CONFIRM_HINT = ("写入台账不可撤销，必须人工确认：先把对账汇总（待结算几笔、多少钱、"
                "有哪些异常）念给用户，用户明确确认后，再以 confirmed=true 调用本工具。")


def _run(cmd: str, **kwargs) -> dict:
    """转发 CLI 处理器（json 模式），把输出解析成 dict。

    MCP stdio 传输用 stdout 传协议帧，处理器内部的 print() 必须
    全程捕获——绝不能泄漏到真实 stdout，否则协议流会被污染。
    """
    ws = Workspace(default_workspace())
    args = types.SimpleNamespace(json=True, **kwargs)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            cli.HANDLERS[cmd](args, ws)
    except cli.ScsError as e:
        return {"ok": False, "error": str(e)}
    except FileNotFoundError as e:
        return {"ok": False, "error": f"文件不存在：{e.filename or e}"}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    text = buf.getvalue().strip()
    if not text:
        return {"ok": True}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"ok": True, "message": text}


# ---------------------------------------------------------------- 工具实现
def scs_init() -> dict:
    """初始化工作区（收件箱/台账/输出/归档/审计目录与默认配置）。幂等，可重复执行。"""
    return _run("init")


def scs_status() -> dict:
    """工作区总览：字段映射是否已配置、收件箱待处理文件、台账统计、最近操作记录。"""
    return _run("status")


def scs_scan() -> dict:
    """扫描收件箱 settlement-inbox，列出每个 Excel 的信息及是否已结算过（按文件哈希判定，防重复结算）。"""
    return _run("scan")


def scs_guess_mapping(file: str) -> dict:
    """识别 Excel 表头，返回字段映射建议（uid/order_no/amount/status 各对应哪一列）。file：.xlsx 的路径。"""
    return _run("guess-mapping", file=file)


def scs_save_mapping(file: str | None = None, mapping: dict | None = None) -> dict:
    """保存字段映射到 config.json。两种方式二选一：
    file：从该 Excel 自动识别并保存；
    mapping：手动指定列名，如 {"uid":"UID","amount":"结算金额","order_no":"订单号"}。"""
    return _run("save-mapping", file=file,
                mapping=json.dumps(mapping, ensure_ascii=False) if mapping else None)


def scs_show_mapping() -> dict:
    """查看当前已保存的字段映射。"""
    return _run("show-mapping")


def scs_reconcile(file: str, mapping: dict | None = None) -> dict:
    """对账：把原始表与台账比对，分六类（待结算/已结算跳过/批内重复/缺UID/金额不一致/需人工复核），
    生成结算预览 Excel 与报告 JSON（在 workspace/output/ 下）。不写台账。
    file：原始 .xlsx 路径；mapping：临时覆盖字段映射（不保存，可选）。
    返回的 summary 应先念给用户确认；写台账请在人工确认后调用 scs_apply。"""
    return _run("reconcile", file=file,
                mapping_json=json.dumps(mapping, ensure_ascii=False) if mapping else None)


def scs_apply(report: str, confirmed: bool = False, force: bool = False) -> dict:
    """把对账报告中的待结算写入台账并归档源文件（不可撤销；幂等：同一文件绝不重复结算）。
    report：scs_reconcile 生成的 报告_批次.json 路径；
    confirmed：必须为 true 才执行——调用前必须先把汇总念给用户并获得明确确认；
    force：重跑已处理过的文件（会重复写台账，仅限纠错，需用户二次确认）。"""
    if not confirmed:
        return {"ok": False, "error": CONFIRM_HINT}
    return _run("apply", report=report, yes=True, force=force)


def scs_import_ledger(file: str, mapping: dict, default_status: str = "settled") -> dict:
    """导入历史结算 Excel 建立台账（首次使用必须先执行，否则已结算/重复判定全部失效）。
    file：历史 .xlsx 路径；
    mapping：列名映射，必须含 uid 和 amount，如 {"uid":"UID","order_no":"订单号","amount":"金额","status":"状态"}；
    default_status：状态列为空或无法识别时按此状态入账，可选 settled / pending / quote。"""
    return _run("import-ledger", file=file,
                mapping=json.dumps(mapping, ensure_ascii=False),
                default_status=default_status)


def scs_query_ledger(uid: str | None = None, limit: int = 50) -> dict:
    """查询台账：传 uid 查该 UID 的结算记录（返回空 = 从未结算过）；不传 uid 返回最近条目与合计统计。"""
    return _run("ledger", uid=uid, limit=limit)


def scs_audit_log(limit: int = 10) -> dict:
    """查询只追加审计日志：所有写操作（对账预览、提交结算、导入台账）都有留痕，含时间、批次、文件哈希、笔数、金额。"""
    return _run("audit", limit=limit)


TOOLS = (scs_init, scs_status, scs_scan, scs_guess_mapping, scs_save_mapping,
         scs_show_mapping, scs_reconcile, scs_apply, scs_import_ledger,
         scs_query_ledger, scs_audit_log)

for _fn in TOOLS:
    mcp.tool()(_fn)


def main() -> None:
    mcp.run()  # stdio 传输


if __name__ == "__main__":
    main()
