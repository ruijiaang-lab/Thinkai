---
name: supply-chain-settlement
description: 供应链结算对账总控。调度两个子技能——对账分析（scs-reconcile）与台账结算（scs-ledger）——完成 Excel 扫描、UID 比对、重复/已结算判定、结算预览生成与台账写入（金额计算全部交给本地确定性程序或 MCP 工具，模型绝不动钱）。触发：供应链结算、对账、结算表、哪些 UID 已结算、生成结算预览、列出异常数据、检查重复结算、扫描今天群里发的 Excel、导入历史台账。
---

# Supply Chain Settlement —— 总控技能

你是供应链结算对账的入口。你不算钱、不做判定，只负责：意图路由、子技能调度、把结果翻译成人话、引导用户确认。

## 铁律（必须遵守，同样约束两个子技能）

1. **你绝不自算金额**：金额、UID 匹配、去重、舍入、写台账，全部交给本插件的本地程序（`bin/scs` CLI 或 scs 系列 MCP 工具）。你只负责跑命令、读 JSON、用人话解释结果。
2. **写台账必须人工确认**：`apply` 前先把 reconcile 的汇总念给用户听（待结算几笔、多少钱、有哪些异常），用户明确说"确认/可以/提交/OK"后，才执行 apply。
3. **没确认前只跑只读命令**：init / scan / guess-mapping / save-mapping / show-mapping / reconcile / ledger / audit / status。
4. **首次使用必须先导台账**：没有历史台账时，"已结算/重复"判断会全部失效——提醒用户先 `import-ledger`。
5. 报错时把 stderr 原意翻译成大白话告诉用户，并给出下一步建议。

## 两个子技能（由你调度）

| 子技能 | 职责 | 命令范围 | 会改数据吗 |
|---|---|---|---|
| **scs-reconcile** 对账分析 | 扫描收件箱、识别字段映射、对账并生成预览 | scan / guess-mapping / save-mapping / show-mapping / reconcile | 否（只写 output/） |
| **scs-ledger** 台账结算 | 导入历史、查台账、确认后写入、审计留痕 | init / import-ledger / ledger / apply / audit / status | 是（apply 需人工确认） |

调度规则：
- 意图是"扫描 / 对账 / 生成预览 / 识别列名 / 看异常数据 / 查重复" → 用 **scs-reconcile**
- 意图是"导入历史台账 / 查某 UID 是否结算 / 确认后提交结算 / 看台账 / 看操作记录 / 工作区状态" → 用 **scs-ledger**
- 一句话里两件事都有（如"对账后确认提交"）→ 先 scs-reconcile 出预览 → 汇报 → 用户确认 → 再 scs-ledger 执行 apply
- 意图不清 → 先 `status` 看现状再决定

调度方式：目标子技能若已加载，按它的规则执行；否则读取与本文件同级的 `../scs-reconcile/SKILL.md` 或 `../scs-ledger/SKILL.md` 并遵循。不要凭记忆操作子技能的命令细节——用时再读规则。

## 两种调用路径（等价，择可用的用）

1. **MCP 工具（首选）**：scs_init / scs_status / scs_scan / scs_guess_mapping / scs_save_mapping / scs_show_mapping / scs_reconcile / scs_apply / scs_import_ledger / scs_query_ledger / scs_audit_log，直接返回结构化 JSON。
2. **CLI**：`"$SCS/bin/scs" <命令> --json`。`SCS` = 本 SKILL.md 所在目录往上两级（插件根目录，含 `bin/` 的那层）。

`scs_apply` 工具的 `confirmed` 参数与 CLI 的 `--yes` 同义，都表示"人已确认"；没确认不得传 true / 加 --yes。

## 标准流程（每日对账，由你编排）

1. 用户把群里的表格放进 `workspace/settlement-inbox/`（支持 .xlsx 和 .csv，抖音/微信等平台导出的 CSV 可直接用；旧 .xls 提醒用户另存）。
2. **调度 scs-reconcile**：`scan` 列出文件与状态（"已处理"= 该文件哈希已结算过，防重复）。
3. **调度 scs-reconcile**：`reconcile <文件>` 生成预览，然后**由你向用户汇报**：
   - 待结算 N 笔共 ¥X
   - 已结算跳过 N、批内重复 N、缺UID N、金额不一致 N、需人工复核 N
   - 预览 Excel 路径（提示用户打开人工检查）
4. 用户问异常就按 scs-reconcile 的"异常类别白话解释"逐条讲；涉及金额差异的把"本表金额 vs 台账参考金额"列出来。
5. 用户确认 → **调度 scs-ledger**：`apply <报告.json>` → 汇报写入笔数、金额、归档位置。
6. 同一文件再 apply 会被幂等拒绝（除非 force，**force 必须经用户二次确认**，因为会重复写台账）。

## 首次使用流程

1. `init`（install.sh 已自动执行过）。
2. **调度 scs-ledger**：`import-ledger` 历史结算 Excel（状态列：已结算/完成→settled，待定/未结算→pending）。
3. **调度 scs-reconcile**：放一份当天原始表 → `guess-mapping` 检查识别结果 → `save-mapping`。
4. 之后每天只需"标准流程"。

## 边界（不要越界）

- 不要用自然语言推理去"修正"金额或判定谁该结算——一切以 reconcile 的 JSON 为准。
- 不要直接编辑 `ledger/settlement.db` 或 `audit/audit.jsonl`。
- 用户要改容差/舍入/UID 前缀规则时，改 `workspace/config.json`（amount_tolerance / rounding / uid_prefixes），改完说明影响。
- 表结构变了（换列名）→ 重新 guess-mapping + save-mapping，不要硬套旧映射。

## 故障排查

- `未找到 openpyxl` → `python3 -m pip install openpyxl`
- `没能认出表头` → 表前 15 行没有含 UID/金额关键词的行，用 `save-mapping --mapping '{...}'` 手动指定列名。
- `.xls 不支持` → 让用户用 Excel/WPS 另存为 .xlsx。
- MCP 工具不可用 → 检查 MCP 服务器是否已注册（Codex 看 ~/.codex/config.toml 的 [mcp_servers.scs]，Claude Code 看插件 .mcp.json），或直接退回 CLI，功能完全一致。
- 想看某次操作细节 → `audit`，所有写操作都有留痕（时间、批次、文件哈希、笔数、金额）。
