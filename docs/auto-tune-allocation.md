# Auto Tune allocation V3 / 资金配置 V3 (methodology v6)

## Scope / 范围

Independent Strategy G now adds ACES risk/state/robustness research without replacing
A–F or this allocation study. See [ACES / 独立 G 代研究说明](aces.md).

Auto Tune and Fine Tune run a bounded joint BUY/SELL threshold and allocation search.
The score model uses existing default composite features, computed once and cached.
Optional factor-weight/indicator-parameter optimization is not part of this joint
loop. Reusing validation-selected A–F feature parameters in earlier allocation
folds would contaminate those folds. A–F metrics, recommendations and curves remain
a separate legacy Current-allocation reference.

The main screen groups the study into the five-toggle combined view below. Toggling
a choice shows or hides its historical test executions and NAV line immediately,
without applying
thresholds to live indicators or placing orders. Detailed research is collapsed.
Fine Tune runs the joint study for its development-selected training window.
Final-test results cannot change that window or any learned configuration.

中文：联合优化买卖触发阈值与资金配置；使用预先固定的默认复合评分，复用缓存，不在此循环中调指标或因子权重。
避免将验证集选出的 A–F 参数带回早期折。主界面合并为以下五种选择，切换即更新历史测试图，
不部署实盘配置、不下单。A–F 表与原推荐折叠保留。Fine Tune 使用开发阶段选中的训练窗口。

## Five strategy choices / 五种策略选择

| Choice / 选择 | Existing study / 对应研究 |
| --- | --- |
| Baseline / 基础 | A |
| Trend / 趋势 | B, C, D; highest validation score / 按验证评分选择 |
| Multi-factor / 多因子 | E, F; highest validation score / 按验证评分选择 |
| Adaptive Budget / 自适应预算 | Selected joint threshold/allocation policy / 联合阈值与预算所选策略 |
| ACES | Selected G policy, or explicitly labeled diagnostic policy / G 所选策略或明确标注的诊断策略 |

Within a family, ties prefer the earlier generation; final-test results never
choose a representative. When allocation has no eligible policy, a fixed
Tuned Fixed (then Fixed) diagnostic fallback remains inspectable. ACES uses its
development-selected `inspected_policy` when no candidate passes selection.
When ACES cannot run full research, it still returns a preset backtest with
the existing score-to-budget rules and risk limits. Missing SPY removes only
the benchmark comparison/reward; losses and zero-trade cash results remain visible.
See [ACES backtest availability](aces.md#backtest-availability--回测结果可用性).

中文：ACES 无法完成完整研究时仍按既有评分资金规则和风险限制回测；缺少 SPY 只停用
基准比较及相对奖励，亏损或零成交的现金结果仍显示。

History and test period are the main inputs. Trade spacing, Fine Tune, presets
and ACES configuration live under collapsed **Advanced tuning settings**;
**Trigger thresholds** also starts collapsed. The Web includes ACES by default,
while the API still requires `aces_config`. Old saved runs remain readable;
rerun to populate the new execution-chart fields.

Each visible choice contributes its test-period price markers and one NAV line to
the combined chart. The price chart uses actual execution dates and fill prices,
including partial sells, stops, risk reductions and final
liquidation. Buy/sell direction is distinguished by marker color and shape only
(green ▲ / orange ▼), with no BUY/SELL text. Each marker shows trade budget as a percentage of **pre-fill NAV**,
holdings as a percentage of **post-fill NAV**, and the originating signal score
in `trade% / S score (Hold%)` format.
Protective and terminal exits have no signal score and display `—`. These new
fields do not change the existing ledger's initial-budget cash-flow percentages.
The API adds optional `test_prices`, `execution_price`, `holding_pct`,
`trade_nav_pct`, and `score` fields; existing consumers remain compatible.

Blocked/HOLD triggers are optionally shown as hollow markers with zero executed
budget and their reason. They are not trades. Selecting/focusing a marker exposes
its details; last-63/252-session views help with dense charts. The combined NAV chart uses
the full test period, starts from normalized capital 1, includes execution fees,
and displays only the exact-date adjusted SPY benchmark when available. Missing
benchmark data is explicit. Reward diagnostics never become fabricated fills.
The technical indicator plot stays expanded above the trigger thresholds, and
research tables remain collapsed below.

中文：每个策略组只按验证评分选版本，同分优先较早代次，不按最终测试收益改选。
无合格配置时，自适应预算固定回退至调优固定策略（其次固定策略）供诊断；ACES 使用
开发阶段选定的诊断策略并标注失败。历史年限和测试年限为主要输入，其余设置及触发阈值默认折叠。
Web 默认包含 ACES，API 仍需显式请求。旧结果可读取，重新调优后补齐新的图表字段。

价格图仅展示测试期，按真实成交日期和价格标注买卖、部分减仓、止损、风险减仓及期末平仓。
买卖方向仅用标记颜色与形状区分（绿色 ▲ / 橙色 ▼），不显示 BUY/SELL 文字。
标记包含成交前净值占比（预算）、成交后净值占比（持仓）及触发分数，格式为 `trade% / S score (Hold%)`；保护性和期末平仓无触发分数，显示 `—`。
旧资金表的初始资金占比口径不变。被阻止/保持仓位的触发可选显示为空心标记，成交预算为零，
不能当作真实交易。合并净值图展示完整测试期的各可见策略实际净值、复权 SPY 和增长目标；包含费用，缺失基准时明确说明。
奖励、机会遗憾等诊断不能伪造为成交。技术指标图默认展开并位于触发阈值上方，研究详情折叠保留。

## Architecture / 架构

FeatureEngine → cached daily scores → threshold crossings → TriggerEvent →
StateEncoder → AllocationPolicy → PortfolioEnvironment → Transition →
portfolio reward + CounterfactualEvaluator → learning reward.

Outer loop: threshold pair → independent training per development fold → frozen
validation → robust aggregate selection → bounded neighboring threshold iteration.
The final test is supplied only after this loop finishes.

## Portfolio accounting / 记账

Every independent train/validation/test segment and episode starts with NAV=1,
cash=1, shares=0. NAV = cash + shares × marked price. Fractional shares, long-only;
no borrowing, leverage, new capital, negative cash, or overselling.

For current NAV N, stock value S, target t and one-way cost c:

```text
buy notional  = (t*N - S) / (1 + t*c), capped at cash/(1+c)
sell notional = (S - t*N) / (1 - t*c), capped at owned stock value
fee          = abs(notional) * c
```

Targets are exposure after fees, not pre-fee notional. Same target within 1e-12
means HOLD without cost. Invalid/nonfinite targets outside [0,1] are rejected.
Buy fees enter average cost basis; partial sales release proportional basis.
Remaining holdings mark unrealized P&L. Terminal liquidation pays exit costs once.

The existing cost_pct_per_side combines commission/spread/slippage. Allocation
metrics are pre-tax, after trading costs; the old full-round-trip tax approximation
does not apply to partial sales. Current-reference tax fields remain separate.
BUDGET_CONSTRAINED indicates a cash cap on naive requested notional and can occur
even when fee-aware full exposure is achieved. It does not imply missed upside.

Ordinary fills require five trading bars since the previous fill. Every incremental
buy also respects window_days. Skips are not queued. Stops and terminal exits
bypass spacing. Decisions use finalized signal-close data; fills use next open.
Gap/entry filters and direction are checked at execution. Added positions can
tighten stops/trails, never loosen them. PositionProtection is shared by actual
and counterfactual simulation.

中文：每段从 100% 现金开始，权益为现金加持仓市值；按扣费后目标仓位求增减仓量。
买入受现金限制、卖出受持仓限制。费用进入成本，浮盈亏进入 NAV，期末费用只扣一次。
普通成交间隔至少五根交易日线，加仓还受买入窗口限制；止损及期末平仓除外。
“现金约束”不等于“错失上涨”；全部持有同一股票时现金为零不会额外受罚。

## State and actions / 状态与动作

State has five causal dimensions:

| Dimension | Boundaries |
| --- | --- |
| Strength | Zero NEUTRAL; magnitude (0,4) WEAK, [4,7) MEDIUM, [7,∞) STRONG, with BUY/SELL sign |
| Exposure | Nearest 0,.2,.4,.6,.8,1; distance ties rounded to 12 decimals prefer lower |
| Cash/NAV | [0,.1), [.1,.3), [.3,.5), [.5,.7), [.7,1], ratio rounded to 12 decimals |
| Unrealized P&L | Below -.15 LOSS_LARGE; [-.15,-.05) LOSS; [-.05,.05] FLAT; (.05,.15] PROFIT; above .15 PROFIT_LARGE |
| Regime | UNKNOWN by default; optional caller-supplied causal BULL/BEAR/SIDEWAYS/UNKNOWN |

Cash and exposure are complementary in this single-stock model; no independent
cross-asset capital is invented. The nominal state space is at most 1050 with
UNKNOWN regime, 4200 with all regimes; many combinations are unreachable.

Actions: targets 0,.2,.4,.6,.8,1 plus explicit HOLD (API null).
BUY masks targets below actual exposure; SELL masks targets above actual exposure.
Neutral permits HOLD only. Masks never authorize trades from rounded exposure.
The legacy-named TriggerEvent.execution_price now contains the known signal-close
reference; actual future open is never passed to policy.choose.

中文：五维状态为强度、仓位桶、现金桶、浮盈亏桶、市场状态，边界如表。
单股现金与仓位互补，不虚构跨股资金占用。未来收益、反事实最优动作及遗憾均不进入状态或策略输入。

## Rewards and regret / 奖励与机会遗憾

```text
portfolio_reward = ln(NAV_next / NAV_before_decision)
learning_reward  = portfolio_reward + benchmark_reward - cagr_penalty
                   - lambda_opportunity * opportunity_regret
sum(portfolio_reward) = ln(final_NAV / initial_NAV)
```

reward remains the actual portfolio log reward for compatibility;
portfolio_reward/reward_before_regret expose it explicitly.
reward_after_regret is used by Q-learning. No terminal bonus, risk metric reward,
or second subtraction from actual NAV is added.

CounterfactualEvaluator clones the actual pre-fill snapshot and replays each
feasible target through the next trigger (or terminal close). It shares the
portfolio solver, fees, protective stops/trails and terminal liquidation.
Candidates respect signal direction, actual cash/holdings, entry filters,
cooldowns, gaps, no leverage, and target limits. HOLD is always feasible.
The actual effective action (HOLD if blocked) is included.

```text
counterfactual_regret = max_feasible(log(next_NAV_action / pre_fill_NAV))
                       - log(next_NAV_actual_action / pre_fill_NAV)
opportunity_regret = max(0, counterfactual_regret)
```

The common pre-fill denominator cancels in regret. Counterfactual actual next NAV
matches actual execution replay; portfolio_reward additionally includes any
signal-close-to-next-open movement. Alternatives are known only after outcome.
A fully invested same-stock BUY before a rally has zero missed-upside regret.
Remaining underexposed before a rally or overexposed before a decline can create
symmetric regret, subject to feasible actions. Costs can make HOLD optimal.

Also report requested-exposure shortfalls separately:

```text
foregone_exposure = max(0, desired_target - actual_exposure)       # BUY
foregone_reduction = max(0, actual_exposure - desired_target)     # SELL
foregone_upside_regret = foregone_exposure * max(0, asset_return)
foregone_downside_regret = foregone_reduction * max(0, -asset_return)
```

These arithmetic diagnostics explain blocked execution, including failed SELL.
They are not added again to feasible-action regret. A blocked, impossible
alternative is not used as a counterfactual learning target.

Reasons: CASH_AVAILABLE_BUT_NOT_USED, EXPOSURE_NOT_REDUCED, FULLY_EXPOSED,
EXECUTION_CONSTRAINED, NO_REGRET. CAPITAL_ALREADY_COMMITTED is not emitted for a
single-stock portfolio: cross-asset attribution is deferred, not fabricated.

中文：真实收益与机会遗憾分开。学习奖励=真实 NAV 对数收益+基准奖励−CAGR 惩罚−λ×可行反事实遗憾。
反事实复用费用、止损、冷却和方向限制，不比较不可能持仓。单股满仓上涨遗憾为零。
未达到请求仓位的上涨/下跌短缺按算术收益另记诊断，不重复计入奖励。
跨股 CAPITAL_ALREADY_COMMITTED 归因留待组合模式，单股不虚构此类损失。

## Non-trigger observations / 未触发观察

ScoreObservation records every finalized bar: both scores, signed thresholds,
trigger status, cash/exposure and outcome-only diagnostics. Engine BUY and SELL
scores are separate positive magnitudes; the allocation report represents SELL
thresholds/scores negatively and adapts at the engine boundary.

Only 0 < distance_to_threshold < opportunity_band produces positive proximity:
proximity = 1 - distance/band. The exact band edge has zero weight.
Already-triggered bars are excluded from missed-threshold attribution.

Horizon is the next bar's open-to-close, bounded by the segment. The final bar has
no forward outcome. This provides non-overlapping daily diagnostic horizons.

```text
threshold_buy_regret  = proximity * max(0, next_open_to_close_return) * cash_ratio
threshold_sell_regret = proximity * max(0, -next_open_to_close_return) * exposure
```

These gross opportunity-band diagnostics are THRESHOLD_MISSED_TRIGGER. They do not
claim an executable trade, ignore future multi-day price paths, and are not added
to counterfactual regret or training reward (avoids double counting overlapping
trigger intervals). Threshold candidates improve through actual independent
execution and validation, not by minimizing these diagnostics.

中文：每根已完成日线记录评分与现金/仓位。只分析距离阈值在有限带内的未触发日；
边界权重为零。前瞻区间固定为下一交易日开盘至收盘，最后一日不越界。
阈值诊断为毛收益机会估计，不等于可成交收益，不与触发区间遗憾重复相加。
阈值是否改善由实际回测与多折验证决定。

## Search, configuration and isolation / 搜索、配置与隔离

Policies: Current single-position score-budget; Fixed targets; Tuned Fixed;
tabular Q-learning. Fixed strong/medium/weak BUY targets are 1/.8/.6;
weak/medium/strong SELL targets are .4/.2/0. Tuned Fixed uses two monotonic
coordinate sweeps on the six-target grid, maximizing training shaped return.

Each threshold pair and each fold trains independently. Scores/features are cached;
Q tables are never carried between incompatible pairs/folds. Threshold search
starts at +6/-6 and tests integer neighbors ±1 in each direction, positive BUY and
negative SELL. Defaults allow two iterations, stopping when the selected pair
does not change; all evaluated candidates are deduplicated. There is no global
optimum guarantee.

Three expanding development folds partition the validation range. Later folds may
train on completed earlier folds. Table train/validation metrics describe the
latest fitted fold; joint_thresholds contains every fold's dates and metrics,
median return/regret, worst return, positive-fold count and threshold stability.
The latest fold's frozen policy is deployed to the final test without refitting.

```text
fold_score = log(final_NAV) + benchmark_reward - cagr_penalty
             - lambda * opportunity_regret
             - .1 * abs(max_drawdown_pct)/100 - .001 * turnover
candidate_score = median(fold_scores) + .1 * worst(fold_scores)
```

Within simplicity_tolerance, prefer simpler allocation, lower fold-score
dispersion, fewer trades, less turnover/regret, then proximity to original thresholds.
Fold-winner BUY/SELL standard deviations expose threshold instability.
No selection rule reads final-test performance.

GET /api/v1/stocks/{code}/auto-tune accepts allocation_config JSON:

```json
{
  "policy_mode": "AUTO",
  "simplicity_tolerance": 0.01,
  "lambda_opportunity": 0.25,
  "opportunity_band": 2,
  "threshold_iterations": 2,
  "validation_folds": 3,
  "q": {
    "alpha": 0.1, "gamma": 0.95,
    "epsilon_start": 0.30, "epsilon_end": 0.02, "epsilon_decay": 0.99,
    "episodes": 100, "random_seed": 42, "minimum_visit_count": 10
  },
  "state": {
    "medium_score": 4, "strong_score": 7,
    "pnl_edges": [-0.15,-0.05,0.05,0.15], "use_regime": false
  }
}
```

V2 defaults to 100 episodes per pair/fold to bound nested-search cost (V1 used
500). All rates/defaults are starting assumptions, not performance-optimal claims.
Episode epsilon=max(end,start*decay^episode). Q update is standard masked
one-step Q-learning; terminal bootstrap zero. Discount is per transition.
visit_count counts distinct training dates; update_count includes repeated
episodes. Below minimum support, frozen Q falls back to Tuned Fixed.

policy_mode limits families (CURRENT; FIXED adds fixed; TUNED_FIXED adds tuned;
AUTO/Q_LEARNING adds Q), but threshold search still runs. Bounds: lambda [0,.5],
band (0,5], iterations integer 1–3, folds integer 2–5, episodes integer 1–2000.
Malformed/unknown settings return 422 before fetching data. No new environment
variables; settings are request-scoped and included in reports.

Training updates require TRAIN and exact study training bounds. Validation/test
use copied immutable Q tables without exploration/update methods. Final test is
supplied after all selection and accepted once. Features, thresholds, windows,
buckets, lambda and Q configuration cannot be chosen from test results.

中文：每阈值对/每折独立训练；默认三折、两轮局部邻域搜索，默认每次 100 回合以限制成本。
验证评分以真实收益为主，遗憾、回撤及换手为小项。近似持平优先简单、稳定、少交易。
训练访问数统计不同日期，低支持回退固定配置。训练区间和阶段双重校验，验证/测试只读且无探索。
设置为请求级 JSON，范围如上，未知或无效值在取数前返回 422。测试不参与任何选择。

## Report and limitations / 报告与边界

Methodology version is 6; older saved results require rerunning Auto Tune.
The API adds joint_thresholds, score_observations, outcome-only transition fields,
regret/capture/cash metrics. Existing fields remain compatible. Comparisons include
Current at original thresholds, Tuned Threshold + Current, Fixed, Tuned Fixed, Q.
Actual return/DD/Sharpe/turnover and regret remain separate in every split.

Regret is in natural-log units; UI shows 100×regret as log points. Daily threshold
diagnostics use arithmetic NAV-equivalent percentage points, not realized loss.
Opportunity capture uses positive final NAV gain / (gain + expm1(upside regret));
undefined 0/0 is null. It is an approximate diagnostic, not a portfolio return.
Cash utilization reports average uninvested cash ratio (100 − mean exposure).

A single stock, sparse state support and repeated development searches limit
statistical inference. Cooldown and stop levels are outside the compact Q state,
so it is a coarse Markov approximation. No cross-asset attribution, deep RL,
tax-lot model, live orders, or optional factor-weight joint search is implemented.
Very short validation folds may have few/no triggers; inspect fold dates/counts.
Buy & Hold regret is not evaluated (reported zero reference), not evidence of
perfect hindsight allocation.

The AAPL 2020–2024 verification used adjusted Yahoo daily data, 2024 as held-out test,
500 explicitly configured episodes and seed 42. It is one implementation validation,
not evidence of robust market outperformance. Avoid retuning after inspecting it.

Rollback: revert the V3 economic reward, API and Web changes together to v5 and
rebuild Web, preserving earlier V1/V2 work. No database migration. CURRENT disables
complex allocation learning but still tunes thresholds, so it is not a v4 rollback.
Temporary screenshots/reports belong outside Git.

中文：版本升至 v6，旧结果需重跑。真实收益和遗憾独立展示；对数遗憾与算术阈值诊断不可混算。
单股、低支持和重复开发试验限制结论；现金桶为单股互补状态。无多股归因、深度强化学习或实盘下单。
AAPL 固定留出测试只作实现验证，不证明稳定超额收益。回滚须协调后端/API/Web 到 v5，无数据库迁移。
本文中英同步；临时截图和验收报告不入库。


## V3 time value and benchmark / 时间价值与基准

Each segment uses calendar days, including weekends, from its first close:
`required_NAV = initial_NAV * (1 + target_cagr) ** (elapsed_days / 365.25)`.
The deficit is `max(0, log(required_NAV / actual_NAV))`; only an increase over
its previous transition endpoint is penalized. Recovery is not penalized.
Marked holdings count in NAV; selling does not earn an extra realized-profit bonus.
An initial cash-only interval is evaluated even before the first trigger, including
windows with no triggers. Actual CAGR is null (shown as Immature) before 90 days.

SPY uses adjusted, dividend-inclusive Yahoo prices. The API enables comparisons
only for US stocks whose price basis is also verified adjusted. Exact daily US
session-close dates must exist throughout each segment; no forward filling and no
unadjusted ^GSPC substitution. Positive alpha above the margin earns a capped bonus,
including losing less than SPY. Positive portfolio profit trailing SPY earns zero
benchmark bonus. A nonpositive portfolio return trailing SPY earns a capped penalty.
Caps apply per transition in log-return units. Future outcomes enter rewards only,
never state or policy input. Fees are already in NAV and are not deducted twice.

Additional request-scoped `allocation_config.economic` defaults:

```json
{
  "target_cagr": 0.30, "lambda_cagr": 0.25,
  "lambda_alpha": 1.0, "lambda_underperform": 0.5,
  "alpha_reward_cap": 0.05, "alpha_penalty_cap": 0.05,
  "alpha_margin": 0.0, "minimum_cagr_days": 90,
  "allowed_max_drawdown": 0.15, "benchmark_missing_policy": "DISABLE"
}
```

Numeric rates are finite fractions in [0,1]; minimum_cagr_days is an integer
in [1,3650]. API drawdown defaults to the existing portfolio drawdown alert setting
converted from percent, unless explicitly overridden; the research default is 15%.
DISABLE explicitly disables the benchmark component for the entire incomplete
segment, reports BENCHMARK_DATA_MISSING and null benchmark returns. BLOCK instead
returns HTTP 422. This fallback keeps non-US analysis available without inventing
comparable S&P returns. Strict benchmark studies should set BLOCK before fitting.

Any validation fold breaching the drawdown limit rejects that candidate before
reward ranking. Profitable median-return candidates take precedence over losing
ones; if all lose, highest actual median return takes precedence. Near ties prefer
simplicity. No eligible candidate means no selection. A final-test risk breach is
flagged and blocks applying thresholds; it never causes test-based reselection.

Reports retain actual returns separately from learning_reward / reward_after_regret,
add benchmark/CAGR/alpha/target-gap metrics, and chart Strategy vs adjusted SPY vs
target NAV with trigger and deficit annotations. The compatibility field
required_nav_for_30pct_cagr follows the configured target, even if changed from 30%.
Buy & Hold is a financial reference, not a trained policy; its opportunity/reward
attribution is not evaluated. The target is a hurdle, not a promised return.

中文：V3 按日历天数计算默认 30% 年增长目标，仅惩罚相邻评估点新增的对数缺口。浮盈计入 NAV，卖出没有额外奖励，费用不重复扣除。首个触发前现金期也评估，不足 90 天的实际 CAGR 显示未成熟。
基准必须是同日美国收盘的复权 SPY，股票也需确认复权口径；不补日期、不用未复权指数替代。跑赢获得封顶奖励，盈利但跑输奖励为零，亏损且跑输受封顶惩罚，亏得更少可获相对奖励。未来结果只进入事后奖励。
economic 是请求级配置；API 默认回撤上限复用现有组合回撤告警百分比，研究默认 15%。DISABLE 明示整段禁用缺失基准，收益为 null；BLOCK 返回 422。验证任一折违反硬回撤限制即排除；测试违规禁止应用但不重新选择。图表展示策略、复权标普及目标曲线；奖励和真实收益分开。中英文已同步。
