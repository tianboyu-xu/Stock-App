"""One causal execution/reward path shared by fixed, tuned and tabular policies."""

from dataclasses import replace

from .allocation_state import StateEncoder
from .allocation_policy import get_valid_actions
from .counterfactual_evaluator import CounterfactualEvaluator, foregone_regret
from .position_protection import PositionProtection
from .score_observation import ScoreObservation
from .allocation_transition import AllocationTransition
from .portfolio_environment import PortfolioEnvironment
from .trigger_event import TriggerEvent, events_from_signals
from .economic_reward import EconomicConfig, BenchmarkDataMissing, evaluate_economic_reward, cagr_snapshot
from datetime import date
from src.services.execution_policy import evaluate_entry, DECISION_EXECUTE


def simulate_allocation(base, signals, start, end, policy, *, cost_pct_per_side,
                        window_days=90, min_trade_gap_bars=5, use_trend_filter=False,
                        use_volume_filter=False, stop_multiple_atr=None, trail_multiple_atr=None,
                        max_entry_gap_atr=None, encoder=None, phase="TEST", observer=None, trace=True,
                        lambda_opportunity=.25, opportunity_band=2.0, economic_config=None, benchmark=None,
                        runtime=None):
    if not 0 <= start <= end < len(base["close"]):
        raise ValueError("invalid allocation simulation range")
    if phase not in {"TRAIN", "VALIDATION", "TEST"}:
        raise ValueError("invalid allocation simulation phase")
    if (observer is not None or getattr(policy, "learning", False)) and phase != "TRAIN":
        raise ValueError("learning is forbidden outside TRAIN")
    env = PortfolioEnvironment(cost_pct_per_side / 100)
    economic_config = economic_config or EconomicConfig()
    segment_dates = base["dates"][start:end + 1]
    if benchmark is None or not benchmark.covers(segment_dates):
        if economic_config.benchmark_missing_policy == "BLOCK":
            raise BenchmarkDataMissing("BENCHMARK_DATA_MISSING: complete exact-date adjusted series required")
        benchmark = None  # Explicit whole-segment fallback, never partial/date-dependent bonuses.
    encoder = encoder or StateEncoder()
    events = events_from_signals(base, signals, start, end)
    by_index = {}
    for event in events:
        by_index.setdefault(event.index, []).append(event)
    records, trades, equity, exposures, executions = [], [], [], [], []
    previous = None
    previous_action = None
    pending = []
    last_trade = last_buy = entry_index = None
    protection = PositionProtection()
    counterfactual = CounterfactualEvaluator()
    contexts = {}
    total_regret = upside_regret = downside_regret = total_learning = 0.0
    upside_count = downside_count = 0
    observations = []
    threshold_buy = threshold_sell = 0.0
    missed_buy_count = missed_sell_count = 0
    holding_bars = 0
    constrained = fallbacks = 0
    total_cagr_penalty = total_benchmark_reward = 0.0
    beat_periods = evaluation_periods = 0
    economic_points = []
    # Account for time in cash before the first trigger, including no-trigger windows.
    if not events or events[0].index > start:
        snapshot = env.mark_to_market(base["close"][start])
        initial_event = TriggerEvent(segment_dates[0], "NEUTRAL", 0., snapshot.last_price, snapshot.last_price)
        previous = AllocationTransition(segment_dates[0], "NEUTRAL", 0., encoder.encode(initial_event, snapshot),
                                        snapshot, None, "INITIAL_CASH_PERIOD", execution_reason="POLICY_HOLD")
        if trace:
            records.append(previous)

    def execute(target, price, i, reason):
        nonlocal last_trade, last_buy, entry_index, constrained
        if runtime:
            env.transaction_cost = runtime.cost(max(start, i - 1))
            price = runtime.price(target, env.mark_to_market(price), price)
        result = env.rebalance(target, price)
        if result.side == "HOLD":
            return result
        if result.reason == "BUDGET_CONSTRAINED":
            constrained += 1
        last_trade = i
        if result.side == "BUY":
            last_buy = i
            if not result.before.shares:
                entry_index = i
        else:
            sold_shares = result.before.shares - result.after.shares
            basis = sold_shares * result.before.average_cost
            trades.append(dict(entry_date=base["dates"][entry_index], exit_date=base["dates"][i],
                               entry_price=result.before.average_cost, exit_price=price * (1 - env.transaction_cost),
                               return_pct=result.realized_profit / basis * 100 if basis else 0,
                               profit=result.realized_profit, bars_held=i - entry_index, exit_reason=reason))
            if not env.shares:
                entry_index = None
        protection.after_fill(result, base["atr"][i - 1] if i > 0 else None, stop_multiple_atr)
        if trace:
            executions.append(dict(date=base["dates"][i], reason=reason,
                                   side=result.side, trade_value=result.trade_value,
                                   transaction_cost=result.transaction_cost, nav=result.after.nav))
        return result

    def blocked(event, target, at_open, i):
        if target is None:
            return "POLICY_HOLD"
        if (event.direction == "BUY" and target < at_open.current_exposure - 1e-12
                or event.direction == "SELL" and target > at_open.current_exposure + 1e-12):
            return "PRICE_DRIFT_DIRECTION_HOLD"
        if abs(target - at_open.current_exposure) <= 1e-12:
            return "SAME_TARGET"
        if last_trade is not None and i - last_trade < min_trade_gap_bars:
            return "TRADE_COOLDOWN"
        if event.direction == "BUY":
            if last_buy is not None and i - last_buy < window_days:
                return "ENTRY_COOLDOWN"
            if use_trend_filter and not (
                event.index > 0 and base["sma200"][event.index] is not None
                and base["sma200"][event.index - 1] is not None
                and event.signal_price > base["sma200"][event.index] > base["sma200"][event.index - 1]
            ):
                return "ENTRY_FILTER"
            if use_volume_filter and not (
                base["vol_sma20"][event.index] is not None
                and base["volume"][event.index] > base["vol_sma20"][event.index]
            ):
                return "ENTRY_FILTER"
            verdict = evaluate_entry(signal_close=event.signal_price, next_open=base["open"][i],
                                     atr=event.atr, max_entry_gap_atr=max_entry_gap_atr)
            if verdict["decision"] != DECISION_EXECUTE:
                return verdict["reason"]
        return None

    def finish(record, date, snapshot, index, state=None, terminal=False):
        nonlocal total_regret, upside_regret, downside_regret, total_learning, upside_count, downside_count
        nonlocal total_cagr_penalty, total_benchmark_reward, beat_periods, evaluation_periods
        if runtime:
            # Terminal adverse-fill prices are execution prices, not the market
            # endpoint. Counterfactuals apply their own adverse exit exactly once.
            snapshot = replace(snapshot, last_price=base["close"][index])
        record.finish(date, snapshot, state, terminal)
        context = contexts.pop(id(record), None)
        if context is not None:
            before, actions, action, first, guard = context
            result = counterfactual.evaluate(
                before, actions, action, snapshot.last_price,
                transaction_cost=runtime.cost(first - 1) if runtime else env.transaction_cost,
                execution_price=base["open"][first], base=base, start=first, end=index,
                protection=guard, stop_multiple_atr=stop_multiple_atr,
                trail_multiple_atr=trail_multiple_atr, terminal=terminal, runtime=runtime)
            record.counterfactual_regret = record.opportunity_regret = result.regret
            record.best_feasible_action = result.best_feasible_action
            record.best_feasible_return = result.best_feasible_return
            record.action_returns = result.action_returns if trace else None
            actual = record.execution.after.current_exposure
            desired = record.requested_target_exposure
            record.asset_forward_return = snapshot.last_price / base["open"][first] - 1
            if desired is not None:
                for key, value in foregone_regret(record.trigger_direction, desired, actual,
                                                  record.asset_forward_return).items():
                    setattr(record, key, value)
            best_target = before.current_exposure if result.best_feasible_action is None else result.best_feasible_action
            if result.regret > 0:
                if best_target > actual:
                    record.missed_upside_regret = result.regret
                    record.opportunity_reason = "CASH_AVAILABLE_BUT_NOT_USED"
                else:
                    record.missed_downside_regret = result.regret
                    record.opportunity_reason = "EXPOSURE_NOT_REDUCED"
            elif actual >= 1 - 1e-12 and record.trigger_direction == "BUY":
                record.opportunity_reason = "FULLY_EXPOSED"
            elif record.foregone_exposure or record.foregone_reduction:
                record.opportunity_reason = "EXECUTION_CONSTRAINED"
        record.economic = evaluate_economic_reward(
            record.trigger_date, date, record.portfolio_before.nav, snapshot.nav,
            initial_date=segment_dates[0], config=economic_config, benchmark=benchmark)
        record.reward_after_regret = (record.portfolio_reward - lambda_opportunity * record.opportunity_regret
                                     + record.economic["benchmark_reward"] - record.economic["cagr_penalty"])
        total_cagr_penalty += record.economic["cagr_penalty"]
        total_benchmark_reward += record.economic["benchmark_reward"]
        if record.duration_days > 0 and record.economic["relative_alpha"] is not None:
            evaluation_periods += 1
            beat_periods += int(record.economic["relative_alpha"] > economic_config.alpha_margin)
        total_regret += record.opportunity_regret
        upside_regret += record.missed_upside_regret
        downside_regret += record.missed_downside_regret
        upside_count += int(record.missed_upside_regret > 0)
        downside_count += int(record.missed_downside_regret > 0)
        total_learning += record.reward_after_regret

    for i in range(start, end + 1):
        if runtime:
            runtime.accrue(env, i, start)
            env.transaction_cost = runtime.cost(max(start, i - 1))
        had_intraday = bool(env.shares)
        waiting = []
        for event, record, choice in pending:
            due = event.index + 1 + (runtime.config.execution.delay_bars if runtime else 0)
            if i < due:
                waiting.append((event, record, choice))
                continue
            at_open = env.mark_to_market(base["open"][i])
            target = choice.target
            if runtime:
                target, record.risk_reason = runtime.risk.allow(target, at_open, i - 1)
                record.allowed_target_exposure = target
            reason = blocked(event, target, at_open, i)
            risk_reduction = runtime and record.risk_reason != "ALLOWED" and target is not None and target < at_open.current_exposure
            if risk_reduction:
                reason = None
            if runtime and runtime.config.execution.skip_every and event.index % runtime.config.execution.skip_every == 0:
                reason = "STRESS_SKIPPED_SIGNAL"
            valid = [a for a in get_valid_actions(record.portfolio_before, event)
                     if a is None or blocked(event, a, at_open, i) in (None, "SAME_TARGET")]
            if runtime:
                valid = [runtime.risk.allow(a, at_open, i - 1)[0] for a in valid]
                if reason == "STRESS_SKIPPED_SIGNAL":
                    valid = [None]
            actual_action = target if reason in (None, "SAME_TARGET") else None
            if actual_action not in valid:
                valid.append(actual_action)  # Continuous Current-policy action.
            contexts[id(record)] = (at_open, valid, actual_action, i, replace(protection))
            if reason is not None:
                result = env.rebalance(at_open.current_exposure, base["open"][i])
            else:
                result = execute(target, base["open"][i], i, "signal")
            record.execution = result
            record.execution_date = base["dates"][i]
            record.execution_reason = reason or result.reason
            record.signal_status = "BLOCKED" if reason not in (None, "SAME_TARGET", "POLICY_HOLD") else "CONFIRMED"
        pending = waiting
        if runtime and i > start and env.shares:
            at_open = env.mark_to_market(base["open"][i])
            cap, risk_reason = runtime.risk.cap(at_open, i - 1)
            if at_open.current_exposure > cap + 1e-12:
                execute(cap, base["open"][i], i, risk_reason)
        # Exposure counts bars with intraday holdings, not an opening liquidation.
        had_intraday = bool(env.shares)
        if env.shares:
            level, reason = protection.exit_level()
            if level is not None and base["low"][i] <= level:
                had_intraday = entry_index == i or base["open"][i] > level
                execute(0, min(base["open"][i], level), i, reason)
        holding_bars += int(had_intraday)
        snapshot = env.mark_to_market(base["close"][i])
        if env.shares:
            protection.close(base["close"][i], trail_multiple_atr)
        equity.append(snapshot.nav)
        exposures.append(snapshot.current_exposure)
        if "buy_threshold" in signals and "sell_threshold" in signals:
            observation = ScoreObservation(
                base["dates"][i], signals["buy_score"][i], -abs(signals["sell_score"][i]),
                signals["buy_threshold"], signals["sell_threshold"], bool(by_index.get(i)),
                snapshot.current_exposure, snapshot.cash / snapshot.nav)
            # Outcome-only diagnostics; the state/policy do not receive observation.
            if i < end:
                observation.evaluate(base["close"][i + 1] / base["open"][i + 1] - 1, opportunity_band)
            threshold_buy += observation.missed_buy_regret
            threshold_sell += observation.missed_sell_regret
            missed_buy_count += int(observation.missed_buy_regret > 0)
            missed_sell_count += int(observation.missed_sell_regret > 0)
            if trace:
                item = observation.to_dict()
                if runtime:
                    item.update(runtime.metadata(i), buy_triggered=signals["buy_signal"][i] is not None,
                                sell_triggered=signals["sell_signal"][i] is not None)
                observations.append(item)
        for event in by_index.get(i, ()):
            if runtime and pending:
                # A new decision supersedes an unfilled delayed order. Never let
                # a closed transition execute later and alter another reward.
                for _, pending_record, _ in pending:
                    pending_record.execution_reason = "SUPERSEDED_DELAYED_ORDER"
                    pending_record.signal_status = "BLOCKED"
                pending = []
            state = encoder.encode(event, snapshot)
            if previous is not None:
                finish(previous, event.timestamp, snapshot, i, state)
                if observer is not None:
                    observer(previous, previous_action, event, snapshot)
            choice = policy.choose(state, event, snapshot)
            # The legacy cash-budget target is continuous; all other policies use the grid.
            if choice.target is not None and not 0 <= choice.target <= 1:
                raise ValueError("policy returned an invalid target")
            if choice.reason == "LOW_SAMPLE_FALLBACK":
                fallbacks += 1
            record = AllocationTransition(event.timestamp, event.direction, event.signed_score,
                                          state, snapshot, choice.target, choice.reason,
                                          q_value=choice.q_value, visit_count=choice.visit_count)
            if runtime:
                record.allowed_target_exposure, record.risk_reason = runtime.risk.allow(choice.target, snapshot, i)
                support = runtime.config.allocation.q.minimum_visit_count
                record.q_confidence = ("UNSEEN" if not choice.visit_count else "LOW" if choice.visit_count < support
                                       else "MEDIUM" if choice.visit_count < 3 * support else "HIGH")
            threshold = signals.get("buy_threshold" if event.direction == "BUY" else "sell_threshold")
            if threshold is not None:
                record.threshold = threshold
                record.distance_from_threshold = abs(event.signed_score - threshold)
            if trace:
                records.append(record)
            previous, previous_action = record, choice.target
            if i < end:
                pending.append((event, record, choice))
    if env.shares:
        execute(0, base["close"][end], end, "segment_end")
    equity[-1] = env.snapshot.nav
    if previous is not None:
        finish(previous, base["dates"][end], env.snapshot, end, terminal=True)
        if observer is not None:
            observer(previous, previous_action, None, env.snapshot)
    elapsed = (date.fromisoformat(segment_dates[-1]) - date.fromisoformat(segment_dates[0])).days
    ending = cagr_snapshot(1., equity[-1], elapsed, economic_config)
    benchmark_return = (benchmark.values[segment_dates[-1]] / benchmark.values[segment_dates[0]] - 1
                        if benchmark else None)
    bench_cagr = (cagr_snapshot(1., 1 + benchmark_return, elapsed, economic_config)["actual_cagr"]
                  if benchmark_return is not None else None)
    if trace:
        for day, nav in zip(segment_dates, equity):
            days = (date.fromisoformat(day) - date.fromisoformat(segment_dates[0])).days
            point = cagr_snapshot(1., nav, days, economic_config)
            economic_points.append(dict(date=day, strategy_nav=nav, required_nav=point["required_nav"],
                                        benchmark_nav=benchmark.values[day] / benchmark.values[segment_dates[0]] if benchmark else None,
                                        cagr_deficit=point["current_cagr_deficit"]))
    peak, max_drawdown = 1., 0.
    for nav in equity:
        peak = max(peak, nav)
        max_drawdown = max(max_drawdown, 1 - nav / peak)
    economic_summary = dict(**ending, cagr_penalty=total_cagr_penalty, benchmark_reward=total_benchmark_reward,
                            benchmark_status="AVAILABLE" if benchmark else "BENCHMARK_DATA_MISSING",
                            benchmark_symbol=benchmark.symbol if benchmark else "SPY", benchmark_return=benchmark_return,
                            benchmark_cagr=bench_cagr,
                            excess_return=(equity[-1] - 1 - benchmark_return) if benchmark_return is not None else None,
                            excess_cagr=ending["actual_cagr"] - bench_cagr if ending["actual_cagr"] is not None and bench_cagr is not None else None,
                            benchmark_beat_periods=beat_periods, total_evaluation_periods=evaluation_periods,
                            benchmark_beat_rate=beat_periods / evaluation_periods if evaluation_periods else None,
                            cagr_target_gap=equity[-1] - ending["required_nav"], maximum_exposure=max(exposures),
                            risk_rejected=max_drawdown > economic_config.allowed_max_drawdown,
                            allowed_max_drawdown=economic_config.allowed_max_drawdown)
    if runtime:
        economic_summary.update(cash_yield=runtime.config.execution.cash_yield,
                                cash_yield_assumption="CONFIGURED_CONSTANT_PROXY" if runtime.config.execution.cash_yield else "ZERO",
                                extreme_volatility_exposure=max((e for e, v in zip(exposures, runtime.base["volatility_regime"][start:end + 1]) if v == "EXTREME"), default=0.))
    return dict(initial_equity=env.initial_nav, equity=equity, trades=trades, holding_bars=holding_bars,
                economic_summary=economic_summary, economic_curve=economic_points,
                transitions=[r.to_dict() for r in records], executions=executions,
                transaction_cost=env.total_transaction_cost, turnover=env.turnover, trade_count=env.trade_count,
                average_exposure=sum(exposures) / len(exposures), allocation_decisions=len(events),
                budget_constrained_decisions=constrained, low_sample_fallbacks=fallbacks,
                opportunity_regret=total_regret, missed_upside_regret=upside_regret,
                missed_upside_count=upside_count, missed_downside_count=downside_count,
                missed_downside_regret=downside_regret, learning_reward=total_learning,
                score_observations=observations,
                threshold_upside_regret=threshold_buy, threshold_downside_regret=threshold_sell,
                threshold_missed_buy_count=missed_buy_count, threshold_missed_sell_count=missed_sell_count,
                trigger_signature=[(e.timestamp, e.direction, e.score) for e in events])
