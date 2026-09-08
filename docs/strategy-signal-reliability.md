# Strategy signal reliability / 策略信号可靠性

## Current scope / 当前范围

These are strategy components, **not a deployed live-trading workflow**. Chart and backtest scoring share formulas; the quality gate, event store, position state and parameter registry are not wired into a production scheduler/API. Existing AI `DecisionSignal` records are a separate system. No broker execution is enabled.

当前实现为策略组件，不代表实盘链路已上线。行情门禁、信号事件、持仓状态、风险计划和参数注册表仍需生产编排；现有 AI `DecisionSignal` 系统不自动受这些保护。不得以组件测试代替生产验收。

```text
indicator_service.compute_indicators -> strategy_scoring
                 ^
strategy_engine.prepare_base_series -> evaluate_signals -> strategy_scoring
                 ^                          ^
          backtester / optimizer -----------+

market_data_quality -> trading_calendar (strict lookup)
signal_event_service / trading_state_service / parameter_registry
    -> strategy_transactions -> SQLite
backtester -> execution_policy
risk_engine -> calculation only
```

## Component contracts / 组件契约

- **Strategy parity:** chart, engine and backtest use the same MACD/KDJ/RSI features. Base-series caches record indicator periods; evaluating different periods rebuilds the features. Custom periods can change previous backtest results because they were formerly ignored. Re-run affected saved optimizations. Generation trend/volume filters remain backtest/engine entry filters; chart threshold markers alone do not establish executable entries.
- **Data quality:** daily bar dates must parse exactly as `YYYY-MM-DD`, `YYYY/MM/DD`, `YYYYMMDD`, or Python date/datetime objects, and be ascending without duplicates. Prices must be finite and positive; open/close must lie within low/high. Required volume must be finite and nonnegative. Unknown markets and unavailable calendars block confirmation. Legacy checkpoint calendar callers retain the default natural-date fallback; the signal gate explicitly requests strict resolution. Metadata is recorded but provider identity and adjustment declarations are not independently verified.
- **Persistence:** strategy writes use SQLite `BEGIN IMMEDIATE` before reading, serializing independent writers. Other database dialects are explicitly unsupported by this helper. Existing tables and stable valid signal IDs are retained; empty or delimiter-containing identity parts are rejected. Strategy versions must identify the generation; conflicting strategy IDs cannot reuse an event identity.
- **Lifecycle:** a PREVIEW/BLOCKED observation can be refreshed and confirmed with final metadata through `record_decision`. Confirmed events cannot revert to preview/blocked; terminal events cannot be revived. Use cancellation/expiry for withdrawal. First confirmation of BUY/SELL permits one notification attempt. HOLD never generates an actionable notification.
- **Delivery:** a false callback result is reported as failure; false results and exception types are persisted in `details`, preserving prior decision details. Exceptions propagate. Repeated runs do not retry delivery. A crash between persistence and delivery can lose an alert: this is **not exactly-once delivery**. Reliable retries require an outbox and an idempotent receiver. Direct `record_decision` followed later by `record_and_notify` does not send the already-confirmed event.
- **Position state:** competing entries within the same ticker/strategy/version/parameter scope cannot both be accepted. Entry fills require a finite positive price. Separate parameter/version scopes remain separate positions; production promotion must reconcile existing exposure rather than assume a new scope is flat.
- **Execution:** next-open prices must be finite and positive. Optional gap limits must be finite and nonnegative; enabled protection requires finite positive ATR. Inclusive gap boundaries and expiry rejection remain unchanged. The caller is still responsible for deriving expiry from the next regular session.
- **Risk:** long BUY plans require a positive stop below the reference entry, finite risk/cap fractions in `[0,1]`, and nonnegative finite existing exposure. Sizing and caps use `maximum_entry` when supplied; it cannot be below the reference price. Sector limits apply when a sector is supplied. Plans are calculations, not orders or guarantees of fill price.
- **Registry:** concurrent promotions leave one production row per exact `(scope_key, strategy_generation)` through the service. Rollback preserves original parent lineage. Candidate/shadow/approved rows remain manually promotable without a production-readiness gate; the status alone is not evidence of readiness. Scope strings remain caller-defined and case-sensitive.

修复重点：自定义指标周期不再被回测忽略；日历不可用时信号门禁阻止确认；非法价格、成交量和止损不能进入执行计划；SQLite 并发写入串行化；预览可在收盘后确认，已执行信号不能复活；通知失败留痕但不自动重发；回滚不再破坏参数祖先链。

## Integration requirements / 尚未完成

Production scheduling must evaluate only the latest eligible completed session, persist sufficient historical input and parameter snapshots, gate position/risk/execution consistently, and avoid replaying every historical trigger as a new alert. The current data hash covers the signal bar, not its entire indicator history. Low-level event persistence does not itself establish data freshness.

Auto Tune does not yet write registry candidates, the existing chart settings do not use production promotion, and no paper replay, production dashboard or production-validation gate is supplied by these components. These are required follow-up implementation tasks, not verified capabilities.

生产接线仍须补齐：仅处理最新有效交易日、完整数据快照、持仓/风控/成交统一编排、可靠投递、候选参数注册、晋升验证和纸面回放。禁止把现有测试内的示例调度循环直接部署为实盘任务。

## Compatibility and rollback / 兼容与回滚

No API fields, environment variables or database tables were added by this correction. Existing valid event IDs remain stable. Invalid numeric inputs, malformed daily date strings, invalid lifecycle transitions and non-SQLite strategy writes now reject explicitly. No UI/report rendering changes are included.

Restore only the changed source files to roll back; no schema migration is required. Retain the database and event history. Rolling back restores the earlier validation/concurrency defects, and does not undo already-recorded events or manually promoted parameters.
