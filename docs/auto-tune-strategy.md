# Auto Tune 触发策略（多因子扩展）

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
   [`src/services/composite_factors.py`](../../src/services/composite_factors.py)，
   `indicator_service.compute_indicators`（技术指标图）与
   `strategy_backtester.compute_composite_signals`（Auto Tune 回测引擎）都调用
   同一份代码，保证图表标记、复合评分与回测信号逐位一致。
2. **无未来函数**：所有因子只用截止当前 bar 的数据（含当前 bar 收盘价，
   与现有信号语义一致，次日开盘成交假设不变）。
3. **opt-in 权重**：每个新因子一组阈值键（触发水平 + 权重），权重为整数点数，
   默认 0 = 不参与评分。经典代际 A–D 的调参范围（`TUNABLE_SCOPES`）只包含
   经典键，新因子权重恒为默认 0，因此 A–D 结果与改造前完全一致。
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
- 回滚：删除扩展因子相关提交即可，经典路径（A–D、旧 8 触发器、阈值面板）
  无行为变化，无需数据迁移。
