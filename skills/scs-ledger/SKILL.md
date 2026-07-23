---
name: scs-ledger
description: 供应链结算对账子技能——台账与结算（状态侧）。导入历史结算表建台账、查询 UID 是否已结算、在人工确认后把待结算写入台账（幂等，同一文件绝不重复结算）、查审计日志与工作区状态。触发：导入历史台账、查某 UID 是否已结算、看台账、提交结算、看操作记录、工作区状态。
---

# scs-ledger —— 台账结算子技能

由总控 `supply-chain-settlement` 调度，也可直接触发。职责范围：**台账与写操作**——唯一允许写台账的技能。

钱款铁律：你绝不自算金额；**写台账必须人工确认**——apply 前先把对账汇总（笔数/金额/异常）念给用户，用户明确说"确认/可以/提交/OK"后才执行。

## 命令（MCP 工具 / CLI 等价）

| 意图 | MCP 工具 | CLI（写操作外的可加 --json） |
|---|---|---|
| 初始化工作区 | `scs_init` | `"$SCS/bin/scs" init` |
| 导入历史台账 | `scs_import_ledger(file=<路径>, mapping={...})` | `import-ledger <文件> --mapping '{...}'` |
| 查某 UID 是否已结算 | `scs_query_ledger(uid="10001")` | `ledger --uid <UID> --json` |
| 看台账 | `scs_query_ledger(limit=50)` | `ledger --limit 50 --json` |
| 提交结算（已确认） | `scs_apply(report=<报告路径>, confirmed=true)` | `apply <报告.json> --yes` |
| 看操作记录 | `scs_audit_log(limit=10)` | `audit --json` |
| 工作区总览 | `scs_status` | `status --json` |

`SCS` = 本 SKILL.md 所在目录往上两级（插件根目录）。

## apply 操作流程（必须遵守）

1. 前提：手上有 scs-reconcile 的 `reconcile` 产出的报告 JSON（`workspace/output/报告_批次.json`）。
2. 先把汇总念给用户：待结算 N 笔共 ¥X、异常情况、预览表路径。
3. 用户明确确认后，才调 `scs_apply(report=<路径>, confirmed=true)`（CLI 为 `--yes`）。没确认不得传 confirmed=true。
4. 成功后汇报：写入笔数、金额、源文件归档位置、台账累计。
5. 同一文件再次 apply 会被幂等拒绝（按文件哈希判重）——这是防重复结算的保护，不要绕过。
6. `force=true` / `--force` 会重跑已处理文件、**重复写台账**，仅限纠错场景，且**必须经用户二次确认**才能执行。

## 导入历史台账（首次使用）

- 没有历史台账，"已结算/重复"判断会全部失效——首次使用先提醒用户准备历史结算 Excel 并导入。
- mapping 必须含 uid 和 amount 两列，例如：`{"uid":"UID","order_no":"订单号","amount":"金额","status":"状态"}`。
- 状态规则：已结算/完成→settled，待定/未结算→pending，其余按 default_status（默认 settled）。
- 缺 UID 或金额无法解析的行会被跳过，导入后把跳过条数报给用户。

## 边界

- 不要直接编辑 `ledger/settlement.db` 或 `audit/audit.jsonl`，一切变更走命令。
- 不要替用户判断"谁该结算"——台账只接受经过确认的 reconcile 报告。
- 报错时把 stderr 翻译成大白话并给下一步建议（如"文件已结算过"→ 解释幂等保护，询问是否确属纠错场景）。
