---
name: scs-reconcile
description: 供应链结算对账子技能——对账分析（只读）。扫描 settlement-inbox 里的 Excel、识别字段映射、与台账比对并分六类（待结算/已结算跳过/批内重复/缺UID/金额不一致/需人工复核），生成结算预览 Excel 和报告 JSON。绝不写台账。触发：扫描今天的 Excel、对账、生成结算预览、识别字段映射、列出异常数据、查重。
---

# scs-reconcile —— 对账分析子技能

由总控 `supply-chain-settlement` 调度，也可直接触发。职责范围：**只读分析**——绝不执行 apply / import-ledger（那是 scs-ledger 的事）。

钱款铁律：你绝不自算金额——金额、匹配、去重全部交给本地程序，你只负责跑命令、读 JSON、用人话解释。

## 命令（MCP 工具 / CLI 等价）

| 意图 | MCP 工具 | CLI（加 --json） |
|---|---|---|
| 扫描今天群里发的表 | `scs_scan` | `"$SCS/bin/scs" scan` |
| 识别字段映射 | `scs_guess_mapping(file=<路径>)` | `guess-mapping <文件>` |
| 保存映射（从文件识别） | `scs_save_mapping(file=<路径>)` | `save-mapping --file <文件>` |
| 保存映射（手动指定） | `scs_save_mapping(mapping={"uid":"UID","amount":"结算金额"})` | `save-mapping --mapping '{...}'` |
| 查看当前映射 | `scs_show_mapping` | `show-mapping` |
| 生成结算预览 | `scs_reconcile(file=<路径>)` | `reconcile <文件>` |

`SCS` = 本 SKILL.md 所在目录往上两级（插件根目录，含 `bin/` 的那层）。

## 对账操作细则

1. 先 `scan` 看文件状态（"已处理"= 该文件哈希已结算过，再 apply 会被拒）。
2. 支持 `.xlsx` 和 `.csv`（UTF-8 / GBK 编码自动识别，平台导出的 CSV 直接放进收件箱即可）；遇到 `.xls` → 提醒用户用 Excel/WPS 另存为 .xlsx。
3. 字段映射未配置（reconcile 报"还没配置字段映射"）→ `guess_mapping` 看识别结果 → `save_mapping` 保存。表结构变了（换列名）→ 重新识别，不要硬套旧映射。
4. `reconcile` 执行后产物在 `workspace/output/`：预览 Excel（`结算预览_批次.xlsx`）+ 报告 JSON（`报告_批次.json`）。

## 汇报模板（交给总控或用户）

- 待结算 N 笔共 ¥X
- 已结算跳过 N / 批内重复 N / 缺UID N / 金额不一致 N / 需人工复核 N（0 笔的可省略）
- 预览 Excel 路径，提示用户打开人工检查
- 若返回 `already_processed=true`：提醒该文件之前处理过，apply 会被幂等拒绝

## 异常类别白话解释（给用户看的）

- **待结算**：本次应该付钱的。
- **已结算跳过**：台账里这笔已经付过，这次不重复付。
- **批内重复**：同一份表里这个 UID+订单出现多次，只算第一笔，其余标记出来。
- **缺UID**：这行没有可识别的 UID，需要人工补全后重跑。
- **金额不一致**：表里金额和台账参考金额对不上（超过容差，默认 0.01 元），需要人工核对。解释时把"本表金额 vs 台账参考金额"并列列出。
- **需人工复核**：金额缺失/无法解析（如写了"待定"），或状态列含"异常/退款/冻结/暂停/退单/作废/冲红"等词。

## 边界

- 只写 `workspace/output/`，绝不碰台账和审计。
- reconcile 完成后把汇总报给调用方（总控或用户），**不要自己发起 apply**——写台账必须人工确认，归 scs-ledger 管。
- 不要用自然语言推理去"修正"金额——一切以 reconcile 的 JSON 为准。
