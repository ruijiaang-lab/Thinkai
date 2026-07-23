# Supply Chain Settlement —— 供应链结算对账 Codex 插件

把"每天下载群里的 Excel → 人工比对 UID → 判断谁该结算 → 做结算表"这套流程，变成一句话就能跑的工具：

> "扫描今天供应链发来的 Excel。" / "帮我检查哪些 UID 已结算。" / "列出所有异常数据。" / "按确认的规则生成结算表。"

## 核心设计：AI 不动钱

| AI 负责 | 确定性程序（本插件）负责 |
|---|---|
| 分析表结构、给字段映射建议 | UID 标准化、精确匹配 |
| 解释异常、引导确认 | 金额计算与舍入（Decimal，全程无浮点误差） |
| 把结果翻译成人话 | 重复判断、已结算判断、文件哈希幂等 |
| | 生成结算 Excel、写台账、审批状态、审计日志 |

**最终结算金额绝不经过大模型。** 模型只是你和这套程序之间的翻译。

## 安装

```bash
cd supply-chain-settlement
./install.sh
```

脚本会自动：检测 Python 与 openpyxl → 把 Skill 装进 `~/.codex/skills/` → 装 Plugin 清单进 `~/.codex/plugins/` → 初始化工作区。

装完后重启 Codex，直接说"扫描今天供应链发来的 Excel"即可。

> 不装也能用：所有功能都在 `bin/scs` 命令行里，见下文。

## 首次使用（3 步）

```bash
# 1. 导入历史结算表，建立台账（之后才能识别"已结算/重复"）
./bin/scs import-ledger ~/Downloads/历史结算表.xlsx \
  --mapping '{"uid":"UID","order_no":"订单号","amount":"金额","status":"状态"}'

# 2. 放一份今天群里发的原始表，识别字段映射
cp ~/Downloads/今日原始表.xlsx workspace/settlement-inbox/
./bin/scs guess-mapping workspace/settlement-inbox/今日原始表.xlsx
./bin/scs save-mapping --file workspace/settlement-inbox/今日原始表.xlsx

# 3. 对账，生成结算预览
./bin/scs reconcile workspace/settlement-inbox/今日原始表.xlsx
```

打开 `workspace/output/结算预览_*.xlsx` 人工检查，确认后：

```bash
./bin/scs apply workspace/output/报告_*.json --yes
```

## 每天怎么用

1. 把群里下载的 Excel 拖进 `workspace/settlement-inbox/`
2. `./bin/scs scan` —— 看哪些待处理（处理过的会自动标记，**同一文件绝不会结算两次**）
3. `./bin/scs reconcile <文件>` —— 生成预览表和报告
4. 人工检查预览表 → `./bin/scs apply <报告.json> --yes`
5. `./bin/scs audit` 随时查所有操作留痕

或者直接在 Codex 里说人话，它会替你跑这些命令。

## 命令全表

| 命令 | 作用 | 会改数据吗 |
|---|---|---|
| `init` | 初始化工作区 | 建目录和默认配置 |
| `scan` | 扫描收件箱，标记已处理/待处理 | 否 |
| `guess-mapping <文件>` | 识别表头，给字段映射建议 | 否 |
| `save-mapping --file <文件>` / `--mapping '<JSON>'` | 保存字段映射 | 改 config.json |
| `show-mapping` | 查看当前映射 | 否 |
| `reconcile <文件>` | 对账 + 生成预览 Excel 和报告 | 只写 output/ |
| `apply <报告> --yes` | 待结算写入台账、归档源文件 | **是（需人工 --yes）** |
| `import-ledger <文件> --mapping '<JSON>'` | 导入历史台账 | 是 |
| `ledger [--uid X]` | 查台账 | 否 |
| `audit` | 查审计日志 | 否 |
| `status` | 工作区总览 | 否 |

所有命令加 `--json` 输出结构化 JSON；加 `--workspace <目录>` 切换工作区。

## 对账结果六类

| 类别 | 含义 |
|---|---|
| 待结算 | 本次应付 |
| 已结算跳过 | 台账里已付过，不重复付 |
| 批内重复 | 同表内 UID+订单多次出现，只算第一笔 |
| 缺UID | 无法识别 UID，人工补 |
| 金额不一致 | 与台账参考金额差异超容差（默认 ¥0.01），人工核 |
| 需人工复核 | 金额无法解析 / 状态含"异常、退款、冻结、暂停、作废、冲红" |

UID 标准化规则（确定性、可复现）：去空白 → 全角转半角（`Ｕ１００８６`→`U10086`）→ 转大写 → 剥前缀（`UID:`/`用户`等，可在 config.json 配）→ 可选正则校验。Excel 把 UID 存成 `10002.0` 也能正确还原。

## 目录结构

```
supply-chain-settlement/
├── .codex-plugin/plugin.json      # Codex 插件清单
├── skills/supply-chain-settlement/
│   └── SKILL.md                   # 给 Codex 的行为规则（含"AI 不动钱"铁律）
├── bin/scs                        # 命令行入口（免安装）
├── src/scs/                       # 确定性引擎源码
│   ├── normalize.py               # UID / 状态标准化
│   ├── money.py                   # Decimal 金额解析与舍入
│   ├── excel_io.py                # 表头识别与字段映射
│   ├── engine.py                  # 对账分桶引擎
│   ├── ledger.py                  # SQLite 台账 + 幂等登记
│   ├── audit.py                   # 只追加审计日志
│   ├── report.py                  # 结算预览 Excel 生成
│   └── cli.py                     # 命令行
├── tests/                         # 40 个测试（pytest）
├── scripts/make_samples.py        # 生成示例 Excel
├── samples/                       # 示例原始表 + 历史台账
├── workspace/                     # 运行时工作区（不入库）
│   ├── settlement-inbox/          # ← 原始表放这里
│   ├── output/                    # 预览表 + 报告
│   ├── ledger/settlement.db       # 台账
│   ├── archive/                   # 已处理文件归档
│   ├── audit/audit.jsonl          # 审计日志
│   └── config.json                # 映射/容差/舍入/UID 规则
└── install.sh
```

## 可调规则（workspace/config.json）

- `amount_tolerance`：金额比对容差，默认 `"0.01"`
- `rounding`：`half_up`（四舍五入，默认）或 `half_even`（银行家舍入）
- `amount_places`：小数位，默认 2
- `uid_prefixes`：标准化时剥离的前缀列表
- `uid_regex`：UID 合法格式正则（null = 不校验）
- `anomaly_status_keywords`：触发人工复核的状态关键词

## 测试

```bash
python3 -m pytest tests/ -v      # 40 passed
```

覆盖：UID 标准化各种脏数据、金额解析与舍入、表头识别、六类分桶判定、容差边界、完整 CLI 流程、**幂等拒绝重复结算**。

## 常见问题

- **旧版 .xls 打不开？** 用 Excel/WPS 另存为 .xlsx。
- **表头认不出来？** `save-mapping --mapping '{"uid":"列名","amount":"列名"}'` 手动指定。
- **同一文件想重跑结算？** `apply <报告> --force`——慎用，会重复写台账，仅限纠错场景。
- **想换电脑？** 带走整个目录即可，台账在 `workspace/ledger/settlement.db`，所有操作在 `workspace/audit/` 有留痕。
