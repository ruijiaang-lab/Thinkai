"""MCP 协议端到端测试：真实拉起 mcp/server.py 子进程，用 stdio 客户端走完整对账流程。

验证：JSON-RPC 握手、工具清单、参数 schema（dict 型 mapping）、
确认门禁（confirmed=false 被拒）、结算写入与审计留痕。
"""
import asyncio
import json
import os
import shutil
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from conftest import ROOT
from scs.samples import build_history_workbook, build_raw_workbook

SERVER = ROOT / "mcp" / "server.py"
IMPORT_MAPPING = {"uid": "UID", "order_no": "订单号", "amount": "金额", "status": "状态"}


async def _scenario(ws, history, inbox_file):
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
        env={**os.environ, "SCS_WORKSPACE": str(ws)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 工具清单完整
            tools = {t.name for t in (await session.list_tools()).tools}
            assert {"scs_init", "scs_scan", "scs_reconcile", "scs_apply",
                    "scs_import_ledger", "scs_query_ledger", "scs_audit_log"} <= tools

            async def call(name, args=None):
                res = await session.call_tool(name, args or {})
                assert not res.isError, f"{name} 协议级错误: {res.content}"
                return json.loads(res.content[0].text)

            # 完整流程
            assert (await call("scs_init"))["ok"] is True
            r = await call("scs_import_ledger",
                           {"file": str(history), "mapping": IMPORT_MAPPING})
            assert r["imported"] == 3

            scan = await call("scs_scan")
            assert len(scan["files"]) == 1

            await call("scs_save_mapping", {"file": inbox_file})

            rep = await call("scs_reconcile", {"file": inbox_file})
            assert rep["summary"]["to_settle"] == 6
            assert rep["summary"]["to_settle_amount"] == "1787.97"
            report_path = rep["output"]["report_json"]

            # 未确认 → 拒绝
            denied = await call("scs_apply", {"report": report_path})
            assert denied["ok"] is False and "确认" in denied["error"]

            # 确认 → 写入
            applied = await call("scs_apply",
                                 {"report": report_path, "confirmed": True})
            assert applied["ok"] is True
            assert applied["settled_count"] == 6

            # 查台账与审计
            ledger = await call("scs_query_ledger", {"uid": "10001"})
            assert ledger["entries"]
            audit = await call("scs_audit_log", {"limit": 20})
            assert any(e.get("action") == "apply_settlement"
                       for e in audit["entries"])
            return True


def test_mcp_stdio_e2e(tmp_path):
    ws = tmp_path / "workspace"
    inbox = ws / "settlement-inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    raw = build_raw_workbook(tmp_path / "raw.xlsx")
    history = build_history_workbook(tmp_path / "history.xlsx")
    shutil.copy(raw, inbox / "raw.xlsx")

    assert asyncio.run(_scenario(ws, history, str(inbox / "raw.xlsx")))
