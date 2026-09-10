# Auto Tune 触发策略（多因子扩展）

当前方法版本为 v6：在联合阈值与配置优化中加入日历 CAGR 门槛、复权标普相对奖励和硬回撤筛选。
目标仓位、增减仓、Q-learning、配置和验证边界见 [资金配置说明](auto-tune-allocation.md)。
下文 v2/v3 章节保留作历史行为与兼容说明；联合优化使用默认评分模型，A–F 表仍为独立原配置参考。

本文说明 Auto Tune 参数寻优与复合评分的多因子扩展：新增因子、触发规则、
代际结构（A–F）、权重语义、阈值默认值与寻优范围，以及为什么不引入外部数据源。

## 1. 背景与目标

旧版 Auto Tune 的触发信号只依赖 8 个触发器（MACD/OBV/KDJ/RSI 各 Buy/Sell），
复合评分由 5 个因子族构成（MACD 百分位、KDJ 交叉、RSI 极端、趋势 regime、
动量改善），满分固定为 10。本次扩展的目标：

- 在**现有日线 OHLCV 数据**内引入更多独立因子，不依赖任何新数据源；
- 新因子以 **opt-in 权重**并入复合评分：权重默认 0，经典代际 A–D 的信号
  与改造前**逐位一致**（由 parity 测试锁定）；
- 图表新增 BOLL / CCI / DMI / MFI 四个触发组，与 MACD/OBV/KDJ/RSI 并列展示；
- Auto Tune 新增代际 E / F，在新因子与经典参数的全集上寻优。

## 2. 设计原则

1. **单一公式实现**：所有扩展因子的计算集中在
   [`src/services/composite_factors.py`](../src/services/composite_factors.py)，
   `indicator_service.compute_indicators`（技术指标图）与
   `strategy_backtester.compute_composite_signals`（Auto Tune 回测引擎）都调用
   同一份代码，保证图表标记、复合评分与回测信号逐位一致。
2. **无未来函数**：所有因子只用截止当前 bar 的数据（含当前 bar 收盘价，
   与现有信号语义一致，次日开盘成交假设不变）。
3. **opt-in 权重**：每个新因子一组阈值键（触发水平 + 权重），权重为整数点数，
   默认 0 = 不参与评分。经典代际 A–D 的调参范围（`TUNABLE_SCOPES`）只包含
   经典键，新因子权重恒为默认 0，因此经典信号公式保持不变。回测成交会计与
   寻优方法另有版本，信号一致不代表历史绩效或推荐参数不变（见第 9 节）。
4. **满分动态化**：`max_buy_score = 10 + 启用因子权重和`（SELL 同理），
   由 API 下发 `max_buy_score` / `max_sell_score`，前端直接渲染，无硬编码。

## 3. 扩展因子定义

| 因子 | 系列 | 买入条件 | 卖出条件 | 默认阈值键（默认值） | 寻优网格 |
| --- | --- | --- | --- | --- | --- |
| BOLL %B | `%B = (close - bold) / (bolu - bold)`，TP 20 日均 ± 2 倍总体标准差（Excel 口径） | %B 上穿低位水平 | %B 下穿高位水平 | `boll_buy_level` (0.1) / `boll_sell_level` (0.9) / `boll_weight` (0) | buy {0.05,0.1,0.15,0.2}，sell {0.8,0.85,0.9,0.95}，权重 {0,1,2} |
| CCI | CCI(14)，典型价、0.015×AVEDEV 口径 | CCI 上穿低位水平 | CCI 下穿高位水平 | `cci_buy_level` (-100) / `cci_sell_level` (100) / `cci_weight` (0) | buy {-150,-120,-100,-80}，sell {80,100,120,150}，权重 {0,1,2} |
| DMI/ADX | Wilder 平滑的 +DI/-DI/ADX(14) | +DI 上穿 -DI 且 ADX ≥ 水平 | +DI 下穿 -DI 且 ADX ≥ 水平 | `adx_min_level` (20) / `dmi_weight` (0) | ADX {15,20,25,30}，权重 {0,1,2} |
| MFI | MFI(14)，典型价 × 成交量资金流量 | MFI 上穿低位水平 | MFI 下穿高位水平 | `mfi_buy_level` (20) / `mfi_sell_level` (80) / `mfi_weight` (0) | buy {15,20,25,30}，sell {70,75,80,85}，权重 {0,1,2} |
| 量能确认 | `volume / SMA20(volume)` | 比值 ≥ 水平且当日收涨 | 比值 ≥ 水平且当日收跌 | `volume_confirm_level` (1.5) / `volume_weight` (0) | {1.2,1.5,2.0,2.5}，权重 {0,1,2} |
| 52 周位置 | `close / rolling_max(high,252)`、`close / rolling_min(low,252)` | 接近 252 日最高（≥ 高位水平） | 接近 252 日最低（≤ 低位水平） | `range52_high_level` (0.95) / `range52_low_level` (1.05) / `range52_weight` (0) | 高位 {0.85,0.9,0.95,1.0}，低位 {1.05,1.1,1.15,1.2}，权重 {0,1,2} |

「上穿」定义为前一根 bar 低于水平、当前 bar 不低于水平（下穿对称），
与图表触发标记共用同一条件。事件型因子（BOLL/CCI/DMI/MFI）触发即得
`权重` 分；量能与 52 周位置为状态型因子，条件成立即得 `权重` 分。
BOLL/CCI/DMI/MFI 同时产生图表触发标记 `boll_buy/sell`、`cci_buy/sell`、
`dmi_buy/sell`、`mfi_buy/sell`；量能与 52 周位置只参与评分，不产生图表标记。

## 4. 复合评分与满分语义

- 经典评分满分 10（MACD 百分位 2 + KDJ 交叉 2 + RSI 极端 2 + regime 2 +
  动量改善 2），逻辑不变。
- 扩展因子按权重加分：`max_buy_score = 10 + Σ(启用权重)`，当前网格权重上限
  为每因子 2 分，理论满分最高 22。
- `buy_breakdown` / `sell_breakdown` 新增 `boll` / `cci` / `dmi` / `mfi` /
  `volume` / `range52` 六个键（默认 0，向后兼容）。
- 权重为 0 时因子不贡献任何分数，也不改变触发判定，保证 A–D 逐位不变。

## 5. 代际结构（A–F）

| 代际 | 名称 | 说明 | 采样范围 |
| --- | --- | --- | --- |
| A | 基线（当前规则） | 默认阈值，无过滤，不寻优 | 默认阈值 |
| B | 基线 + 趋势过滤 | Close > SMA200 且 SMA200 上行才买入 | 经典键 |
| C | 趋势 + ATR 风控 | B + ATR 止损与移动止盈 | 经典键 |
| D | 最终评分策略 | 全经典参数寻优 + 趋势过滤 + 成交量确认 + ATR 风控 | 经典键 |
| E | 多因子评分 | 经典 + 扩展因子权重/水平寻优，无额外过滤 | 全部键 |
| F | 多因子 + 风控 | E + 趋势过滤 + 成交量确认 + ATR 止损/移动止盈 | 全部键 |

- A–D 的 `TUNABLE_SCOPES` 限定为经典键（原有 10 个键、原有顺序），
  采样序列与改造前完全一致，结果确定且可复现。
- 推荐逻辑不变：验证集「足够好中最简单」优先，E/F 与 A–D 同台比较。

## 6. API 与 Web 变更

- `GET /api/v1/stocks/{code}/indicators` 新增 16 个阈值查询参数
  （`boll_buy_level`、`boll_sell_level`、`boll_weight`、`cci_buy_level`、
  `cci_sell_level`、`cci_weight`、`adx_min_level`、`dmi_weight`、
  `mfi_buy_level`、`mfi_sell_level`、`mfi_weight`、`volume_confirm_level`、
  `volume_weight`、`range52_high_level`、`range52_low_level`、`range52_weight`）。
- `GET /api/v1/stocks/{code}/auto-tune` 返回 6 代（A–F）；策略 `params.thresholds`
  含调优后的扩展因子键，前端参数面板按
  `AUTO_TUNE_PARAM_ORDER` 顺序展示（带默认值对照）。
- Web 技术指标图：新增 BOLL/CCI/DMI/MFI 触发组（开关、图例、标记）、
  扩展因子阈值面板（权重为 0 时标注不参与评分）、复合评分明细按因子标签
  （中英双语）动态渲染。

## 7. 免费外部数据源评估（结论：暂不接入）

| 数据源 | 提供内容 | 结论 |
| --- | --- | --- |
| Stooq | 多市场日线 OHLCV（免费 CSV） | 与现有日线重叠，无新增因子维度 |
| FRED | 宏观序列（利率、CPI 等） | 非 point-in-time、更新滞后、粒度与个股回测不匹配，易引入前视偏差 |
| Yahoo Finance | 日线 + 基础财务 | 财务数据无历史 point-in-time 快照，回测会引入幸存者/前视偏差 |
| 免费基本面 point-in-time | — | 基本不存在免费且历史对齐的现成服务 |

因此本期不接入任何外部数据源；如后续需要宏观/基本面因子，优先评估
付费 point-in-time 数据（如 Refinitiv / Sharadar），并需在回测引擎中
增加数据对齐与滞后规则。

## 8. 风险与回滚

- **A–D 回归**：parity 测试锁定「新因子权重默认 0 时输出逐位一致」，
  任何公式改动需先跑 `pytest tests/test_strategy_backtester.py tests/test_indicator_service.py -m "not network"`。
- **调参空间膨胀**：E/F 采样全部键，耗时高于 A–D；如需收缩可调整
  `SAMPLED_CANDIDATES` 或 `TUNABLE_GRID` 网格。
- **满分语义**：旧客户端若硬编码满分 10 会显示不一致；当前 Web 端已改用
  API 的 `max_buy_score` / `max_sell_score`。
- 多因子扩展回滚需同步还原共享公式、API 字段和 Web 阈值控件；无数据库迁移。
  回测方法更新的兼容性和回滚见下一节。

## 9. 回测会计与验证方法 v2（历史版本；当前预算规则见第 10 节）

响应新增 `methodology_version=2`。旧结果的退出成本、敞口、基准收益和
Fine Tune 选窗依据存在错误，必须重新运行；新旧结果不能作为同口径绩效比较。
Web 保留旧结果、方案及其运行设置，但提示重新运行后才能应用寻优参数。

### 成交、权益与敞口

- 退出费用只在 `close_trade` 中扣一次；入场成本计入买价。
- 初始资金 `initial_equity=1.0` 在首根 bar 之前确定；每天一个权益点，
  末日强制平仓后更新最后一点。总收益、CAGR、首日收益、最大回撤
  与累计收益图都基于初始资金，避免除以首日收盘权益抵消入场成本。
- 买入持有在区间首日开盘买入、末日收盘卖出，计算约定与策略相同。
  因首日涨跌及买入成本，基准累计收益图的第一个点不一定为 0%。
- `exposure_pct` 累计存在盘中持仓的交易日，不在平仓时清零；
  老持仓开盘即卖出的当天不计入，盘中止损当天计入。这是日线近似。
- 入场 ATR 只取上一根已收盘 bar；初始止损在入场当天生效。
  移动止盈使用持仓期间最高收盘价，从下一根 bar 生效。
  固定止损与移动止盈同时有效时取较高退出价，跳空穿越按开盘价成交。

### 训练、滚动验证与保留测试

1. 先预留历史尾部最终测试段。裁剪历史后仍须满足最低 600 根日线。
2. 普通 Auto Tune 最后一个 fold 保持原训练/验证边界；最多再从训练历史中
   向前构建两个不重叠的验证块，每块长度至少为
   `max(原验证段长度, 252, 3 × entry_gap_bars)`，前面至少留 60 根训练日线。
   每个 fold 的训练终点早于自身验证起点，后续训练可包含更早 fold 的验证历史。
3. 每个 fold 独立进行随机搜索、训练集邻域搜索和 Top-K 验证，最终参数采用
   最新 fold 的选择。Top-K 来自全部随机候选与爬山候选的去重集合，避免重复
   参数夸大原有 `param_robustness` 平台比例。
   信号缓存只保留当前代际/验证折的候选，避免多窗口扫描持续累积大数组。
4. 代际比较使用 `median(fold validation score) - std(fold validation score)`，
   仍按 0.05 容忍度优先选择简单代际。返回实际 fold 边界与离散程度；
   历史不足时使用较少 fold，不声称单 fold 结果有跨时期一致性。
   同时报告正收益 fold 数、最差 CAGR 与满足交易数门槛的 fold 数；
   没有合格 fold 时推荐原因标为证据不足，而非宣称基线已经足够。
5. Fine Tune 的滑动训练窗口统一使用同一验证范围。只有验证期足够长时才
   分为多个向前验证块，每块至少 `max(252, 3 × entry_gap_bars)` 根；
   普通长度历史通常只有一个 Fine Tune 验证块。后续 fold 的训练从选中窗口
   起点扩展至前一个验证块末尾。窗口、代际、参数只依据验证分数选择，
   最终胜出窗口单独执行一次测试模拟。
6. 所有自动选择先完成，再生成测试报告。普通 A–F 的固定参数测试结果用于
   描述性对比，测试分数、置信区间与基准不参与自动推荐。

查看测试结果后继续手动选择代际、改设置并反复运行，会把保留测试用于
人工选择；程序内隔离不能消除这种偏差。重叠的 Fine Tune 窗口也不是独立样本。

### 目标与不确定性

目标函数改为以下成本后指标，保留最低交易次数门槛：

```text
0.60 × clamp(Sharpe, -3, 3)
+ 0.40 × clamp(CAGR百分数 / 25, -2, 2)
- 0.60 × abs(最大回撤百分数) / 100
```

不再叠加 Sortino、盈亏比、胜率和平均单笔收益，也不再追求固定每年 4 笔。
这些指标仍用于展示。换手成本已在成交中计入，不再重复扣费。
最低交易数为 `max(3, round(区间年数))`；不满足时返回不合格分数。

`test_confidence`（Fine Tune 为 `final_test.confidence`）仅在固定参数测试完成后
对每日净收益做 400 次圆形块 bootstrap，块长为 `ceil(n ** (1/3))`。
返回 Sharpe 的 95% 百分位区间、有效重采样次数、块长及正 Sharpe 重采样占比。
圆形块保留块内时间关联并允许尾首环绕，方法背景见
[arch 时间序列 bootstrap 文档](https://bashtage.github.io/arch/bootstrap/timeseries-bootstraps.html)。
这是对已观察路径的条件性描述，不是未来获利概率，不修正多重调参偏差；
未实现 Deflated Sharpe。少于 60 根日线、少于 3 笔交易、零方差或无效权益时，
返回 `available=false` 和原因，不生成看似精确的区间。

### API、显示和验证

- Fine Tune `sweep` 使用 `validation_score`、`validation_cagr`、
  `validation_sharpe`、`validation_max_dd`、`validation_trades`。
  验证 CAGR/Sharpe 是各 fold 中位数，回撤取最差 fold，交易数为 fold 合计。
  兼容保留的旧 `test_*` 字段为 `null`，不能将验证绩效伪装成测试绩效。
- `selection_basis=validation`；`final_test` 包含胜出窗口及代际标识、
  `metrics`、`equity` 和 `confidence`。Web 柱图按验证分数绘制，
  验证明细与最终测试摘要分开显示，中英文使用同一语义。
- 现有策略、阈值与风险字段保持；新诊断字段通过 API schema 保留。
  Electron 使用同一 Web 前端，不需要改变桌面端协议或启动入口。
- 没有新增环境变量、数据库结构、外部行情服务或模型调用。
- 建议验收命令：

```bash
python -m pytest tests/test_strategy_backtester.py tests/test_indicator_service.py tests/test_indicator_optimizer_validation.py tests/test_backtest_statistics.py tests/test_auto_tune_api_contract.py -m "not network"
cd apps/dsa-web
npm run lint
npm run build
npm test -- src/components/history/__tests__/StockIndicatorChart.test.tsx src/api/__tests__/stocks.test.ts
```

确定性回归覆盖费用、信号退出、入场日止损、跟踪止损、跳空、终端清仓、
敞口累计、基准收益与图表一致、最终测试扰动不改变推荐，以及 API 字段保留。

多股票/行业共用参数、市场状态归因、AI YAML 技能版本与历史推荐归因、
局部参数热图仍需后续独立设计，不能从单股票复合评分结果推导这些统计。
回滚需同步还原后端、API schema、Web 类型/显示/版本判断并保留用户方案；
无需数据库迁移，但回滚会恢复旧方法缺陷，已有 v2 结果应另存备查。

## 10. 预算与低频执行 v3 / Budget and trade spacing

`methodology_version=3`：A–F、Fine Tune 的训练、验证和最终测试均使用相同预算规则。
每个独立回测区间从 100% 现金开始；区间内部不补充预算。旧结果与方案保留，需重新
运行才能应用参数。交易触发仍使用现有复合评分，预算只改变执行与收益计算。

- 买入比例为 `clamp(买入评分 / 理论满分, 25%, 100%)`，按信号收盘时的当前权益分配，
  满分包含已启用扩展因子权重。该比例是固定启发式，不代表获利概率或经验证的最优仓位。
- 单一多头持仓，不加仓、不借款、不做空；已有持仓的买入信号跳过。现金耗尽时买入
  成交比例为 0%。买入费用包含在分配金额内，剩余现金不参与持仓涨跌。
- 卖出全部持仓，扣除费用后的所得回到现金，可用于下一次买入。权益为现金加持仓市值，
  收益相对初始资金计算；税后近似收益按实际分配比例加权后复利，不再把部分仓位当成满仓。
  现有税后指标仍是独立展示估算，不在税前执行账户逐笔扣税。
- 普通买卖成交至少间隔 5 根交易日 bar；两次买入还需满足所选 `window_days`。
  冷却期信号直接跳过、不排队；止损、移动止盈、窗口结束平仓不受冷却期限制。
- API 新增 `strategies[].test_decisions` 和 `fine_tune.final_test.decisions`。
  Web 的各代策略和 Fine Tune 最终测试提供可展开的预算明细：信号/成交日期、方向、
  建议预算比例、实际成交比例、剩余现金比例、成交/跳过原因。百分比全部相对初始预算，
  盈利后可超过 100%；建议卖出为信号收盘市值，实际卖出为成交价扣费后的现金流。
- 标普策略时点基准复用原交易的仓位比例；买入持有基准仍为满仓。时点基准沿用已有
  日线映射近似（同日止损不能按另一市场的盘中价格精确重放）。
- 没有新增环境变量或数据库迁移；Electron 使用相同 Web。回滚应同时恢复回测、寻优、
  API/Web 字段与方法版本；保留用户旧方案，重新生成结果。

English: Each independent simulation starts with 100% cash. A–F and Fine Tune buy
25–100% of current equity using the signal score divided by its theoretical maximum
(including enabled extra factors). This fixed sizing heuristic is not a calibrated
probability or a demonstrated optimal allocation. The simulation holds one long
position at a time, without pyramiding, borrowing, or shorting. An unfunded buy is
skipped; sells liquidate the position and replenish cash. Fees are included in the
cash flows, and idle cash does not earn the stock return. Ordinary fills are spaced
at least five trading bars apart, in addition to the selected entry interval.
Cooldown signals are skipped, not queued; protective and terminal exits are exempt.
The bilingual test ledger shows suggested and executed percentages of initial
budget, remaining cash, and skip reasons. After-tax comparison compounds returns
weighted by allocation; it remains an estimate separate from the pre-tax cash ledger.
Saved v2 results must be rerun. No environment configuration or database migration is
required. Revert the backend, API, Web, and methodology version together to roll back.
