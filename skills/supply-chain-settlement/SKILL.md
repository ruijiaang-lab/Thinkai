---
name: supply-chain-settlement
description: 供应链日常结算对账插件。扫描 settlement-inbox 里的 Excel 原始表，与历史台账比对，判断哪些 UID 应结算/已结算/重复/缺UID/金额异常，生成结算预览 Excel，用户确认后写入台账并留审计日志（金额计算全部由本地确定性程序完成，模型不算钱）。触发：供应链结算、对账、结算表、哪些 UID 已结算、生成结算预览、列出异常数据、检查重复结算、扫描今天群里发的 Excel、导入历史台账。
---

# Supply Chain Settlement —— 供应链结算对账

## 铁律（必须遵守）

1. **你绝不自算金额**：金额、UID 匹配、去重、舍入、写台账，全部交给本插件的本地程序（`bin/scs`）。你只负责跑命令、读 JSON、用人话解释结果。
2. **写台账必须人工确认**：`apply` 前先把 reconcile 的汇总念给用户听（待结算几笔、多少钱、有哪些异常），用户明确说"确认/可以/提交/OK"后，才执行 `apply <报告> --yes`。
3. **没确认前只跑只读命令**：`init / scan / guess-mapping / save-mapping / show-mapping / reconcile / ledger / audit / status`。
4. **首次使用必须先导台账**：没有历史台账时，"已结算/重复"判断会全部失效——提醒用户先 `import-ledger`。
5. 报错时把 stderr 原意翻译成大白话告诉用户，并给出下一步建议。

## 路径约定

- `SCS` = 本 SKILL.md 所在目录往上两级（插件根目录，含 `bin/` 的那层）。
- 命令入口：`"$SCS/bin/scs"`
- 工作区：`"$SCS/workspace/"`
  - `settlement-inbox/` 用户放原始 Excel 的地方
  - `output/` 结算预览 Excel（`结算预览_批次.xlsx`）+ 报告 JSON（`报告_批次.json`）
  - `ledger/settlement.db` 台账（SQLite，单一事实来源）
  - `audit/audit.jsonl` 只追加审计日志
  - `archive/` 已处理文件归档
- 所有命令加 `--json` 输出结构化 JSON（放在子命令前后均可）。

## 命令速查

| 用户意图 | 命令 |
|---|---|
| 扫描今天群里发的表 | `"$SCS/bin/scs" scan` |
| 识别字段映射 | `"$SCS/bin/scs" guess-mapping <文件>` |
| 保存字段映射 | `"$SCS/bin/scs" save-mapping --file <文件>` |
| 手动指定映射 | `"$SCS/bin/scs" save-mapping --mapping '{"uid":"UID","amount":"金额"}'` |
| 生成结算预览 | `"$SCS/bin/scs" reconcile <文件> --json` |
| 确认后写台账 | `"$SCS/bin/scs" apply <报告.json> --yes` |
| 查某 UID 是否已结算 | `"$SCS/bin/scs" ledger --uid <UID>` |
| 看台账 | `"$SCS/bin/scs" ledger --limit 50` |
| 看操作记录 | `"$SCS/bin/scs" audit` |
| 导入历史台账 | `"$SCS/bin/scs" import-ledger <历史Excel> --mapping '{"uid":"UID","order_no":"订单号","amount":"金额","status":"状态"}'` |
| 工作区总览 | `"$SCS/bin/scs" status` |

## 标准流程（每日对账）

1. 用户把群里的 Excel 放进 `workspace/settlement-inbox/`（仅支持 .xlsx；旧 .xls 提醒用户另存）。
2. `scan` 列出文件与状态（"已处理"= 该文件哈希已结算过，防重复）。
3. `reconcile <文件> --json` 生成预览，向用户汇报：
   - 待结算 N 笔共 ¥X
   - 已结算跳过 N、批内重复 N、缺UID N、金额不一致 N、需人工复核 N
   - 预览 Excel 路径（提示用户打开人工检查）
4. 用户问异常就按下方"异常类别白话解释"逐条讲；涉及金额差异的把"本表金额 vs 台账参考金额"列出来。
5. 用户确认 → `apply <报告.json> --yes` → 汇报写入笔数、金额、归档位置。
6. 同一文件再 `apply` 会被幂等拒绝（除非 `--force`，**`--force` 必须经用户二次确认**，因为会重复写台账）。

## 首次使用流程

1. `"$SCS/bin/scs" init`（install.sh 已自动执行过）。
2. 拿一份历史结算 Excel → `import-ledger`（状态列：已结算/完成→settled，待定/未结算→pending）。
3. 放一份当天原始表 → `guess-mapping` 检查识别结果 → `save-mapping --file`。
4. 之后每天只需"标准流程"。

## 异常类别白话解释（给用户看的）

- **待结算**：本次应该付钱的。
- **已结算跳过**：台账里这笔已经付过，这次不重复付。
- **批内重复**：同一份表里这个 UID+订单出现多次，只算第一笔，其余标记出来。
- **缺UID**：这行没有可识别的 UID，需要人工补全后重跑。
- **金额不一致**：表里金额和台账参考金额对不上（超过容差，默认 0.01 元），需要人工核对。
- **需人工复核**：金额缺失/无法解析（如写了"待定"），或状态列含"异常/退款/冻结/暂停/作废/冲红"等词。

## 边界（不要越界）

- 不要用自然语言推理去"修正"金额或判定谁该结算——一切以 reconcile 的 JSON 为准。
- 不要直接编辑 `ledger/settlement.db` 或 `audit/audit.jsonl`。
- 用户要改容差/舍入/UID 前缀规则时，改 `workspace/config.json`（amount_tolerance / rounding / uid_prefixes），改完说明影响。
- 表结构变了（换列名）→ 重新 guess-mapping + save-mapping，不要硬套旧映射。

## 故障排查

- `未找到 openpyxl` → `python3 -m pip install openpyxl`
- `没能认出表头` → 表前 15 行没有含 UID/金额关键词的行，用 `save-mapping --mapping '{...}'` 手动指定列名。
- `.xls 不支持` → 让用户用 Excel/WPS 另存为 .xlsx。
- 想看某次操作细节 → `audit`，所有写操作都有留痕（时间、批次、文件哈希、笔数、金额）。
