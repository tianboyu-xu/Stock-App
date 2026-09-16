"""MATR: point-in-time macro selection above existing Auto Tune families."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta
import hashlib
import json
import math
from statistics import fmean

from data_provider.macro_data import (
    MacroDataError, MacroDataProvider, MacroDataUnavailable, MacroSnapshotIntegrityError, freeze_json,
    quarter_for_date, quarter_start,
)
from data_provider.us_index_mapping import is_us_stock_code
from src.core.trading_calendar import get_effective_trading_date, get_market_now
from src.services.allocation.economic_reward import EconomicConfig
from src.services.macro_execution import (
    FAMILY_KEYS, WINDOW_BARS, MacroExecutionEngine, MacroExecutionUnavailable, _max_drawdown,
)
from src.services.macro_router_model import DEFAULT_SETTINGS, select_strategy
from src.services.strategy_backtester import DEFAULT_COST_PCT_PER_SIDE


ROUTER_VERSION = 2


def unavailable_report(reason):
    return dict(strategy_key="MATR", version=ROUTER_VERSION, status="UNAVAILABLE",
                reason=reason, current=None, correlations=[], history=[], warnings=[])


def _scope(symbol, economic_config, cost):
    # History length is deliberately excluded: extending requested history must
    # not silently change an already-published current-quarter recommendation.
    context = dict(version=ROUTER_VERSION, symbol=symbol.upper(),
                   economic=asdict(economic_config), cost_pct_per_side=cost,
                   router_settings=asdict(DEFAULT_SETTINGS), window_bars=WINDOW_BARS,
                   price_basis="ADJUSTED_TOTAL_RETURN")
    return hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()[:24]


def _decision(rows, snapshot, cache_dir, scope, *, freeze):
    path = cache_dir / "decisions" / scope / f"{snapshot.quarter}.json"
    if path.exists():
        return _validate_decision(freeze_json(path, {}), snapshot, scope)
    result = select_strategy(rows, dict(quarter=snapshot.quarter, features=snapshot.features), list(FAMILY_KEYS))
    decision = dict(result, quarter=snapshot.quarter,
                    feature_quarter=quarter_for_date(quarter_start(snapshot.quarter) - timedelta(days=1)),
                    as_of=snapshot.decision_date, snapshot_id=snapshot.snapshot_id,
                    regime=dict(key=snapshot.regime, factors=snapshot.factor_scores),
                    missing_features=list(snapshot.missing_features), scope=scope,
                    training_start=rows[0]["quarter"] if rows else None,
                    decision_kind="frozen_quarter_selection" if freeze else "walk_forward_research")
    if freeze and decision["available"]:
        decision = _validate_decision(freeze_json(path, decision), snapshot, scope)
    return decision


def _validate_decision(decision, snapshot, scope):
    if (decision.get("scope") != scope or decision.get("quarter") != snapshot.quarter
            or decision.get("snapshot_id") != snapshot.snapshot_id
            or decision.get("selected_strategy") not in (*FAMILY_KEYS, "CASH")
            or not decision.get("available")):
        raise MacroSnapshotIntegrityError("Frozen MATR decision failed identity validation")
    return decision


def _family_statistics(outcome, family):
    result = outcome["families"][family]
    active_windows = sum(bool(window["trades"]) for window in result["windows"])
    holding_bars = sum(window["holding_bars"] for window in result["windows"])
    return dict(return_pct=result["return_pct"], max_drawdown_pct=result["max_drawdown_pct"],
                trade_count=result["trade_count"], active_windows=active_windows,
                completed_windows=outcome["completed_windows"], holding_bars=holding_bars,
                exposure_rate_pct=100 * holding_bars / len(outcome["dates"]))


def _quarter_report(outcome, decision):
    family = decision["selected_strategy"]
    result = outcome["families"][family]
    spy = outcome["families"]["SPY_BuyHold"]
    oracle = max(outcome["families"][key]["utility"] for key in (*FAMILY_KEYS, "CASH"))
    windows = []
    # Cash still records every window, so zero trades never look like missing data.
    source_windows = result["windows"] if family != "CASH" else outcome["families"][FAMILY_KEYS[0]]["windows"]
    for window in source_windows:
        trade = window["trades"][0] if family != "CASH" and window["trades"] else None
        windows.append(dict(
            start_date=window["start_date"], end_date=window["end_date"], strategy_key=family,
            entry_date=trade["entry_date"] if trade else None, exit_date=trade["exit_date"] if trade else None,
            entry_price=trade["entry_price"] if trade else None, exit_price=trade["exit_price"] if trade else None,
            exit_reason=trade["exit_reason"] if trade else None,
            net_return_pct=window["return_pct"] if family != "CASH" else 0.,
            spy_return_pct=window["benchmark_return_pct"], utility=window["utility"] if family != "CASH" else 0.,
            params=window["params"] if family != "CASH" else {},
            trained_through=window["trained_through"] if family != "CASH" else None,
        ))
    return dict(quarter=outcome["quarter"], selected_strategy=family, regime=decision["regime"]["key"],
                complete=outcome["complete"], net_return_pct=result["return_pct"],
                spy_return_pct=spy["return_pct"], regret=max(0., oracle - result["utility"]),
                utility=result["utility"], predicted_utility=next(
                    (item["expected_utility"] for item in decision["ranking"] if item["strategy_key"] == family), 0.),
                windows=windows, decision=decision,
                **{key: value for key, value in _family_statistics(outcome, family).items()
                   if key != "return_pct"},
                family_returns={key: outcome["families"][key]["return_pct"] for key in (*FAMILY_KEYS, "CASH")},
                family_statistics={key: _family_statistics(outcome, key) for key in (*FAMILY_KEYS, "CASH")},
                family_utilities={key: value["utility"] for key, value in outcome["families"].items()})


def _family_comparison(outcomes, family):
    """Compare each causal family on exactly the router's completed quarters."""
    equity, nav = [], 1.
    for outcome in outcomes:
        equity.extend(nav * value for value in outcome["families"][family]["equity"])
        nav = equity[-1]
    statistics = [_family_statistics(outcome, family) for outcome in outcomes]
    window_count = sum(row["completed_windows"] for row in statistics)
    session_count = sum(len(outcome["dates"]) for outcome in outcomes)
    return dict(strategy_key=family, oos_quarters=len(outcomes),
                total_return_pct=(nav - 1) * 100, max_drawdown_pct=100 * _max_drawdown(equity),
                trade_count=sum(row["trade_count"] for row in statistics),
                active_window_rate_pct=100 * sum(row["active_windows"] for row in statistics) / window_count,
                exposure_rate_pct=100 * sum(row["holding_bars"] for row in statistics) / session_count)


def _diagnostics(history, outcomes, benchmark):
    complete = [row for row in history if row["complete"]]
    if not complete:
        return None
    evaluated = {row["quarter"] for row in complete}
    complete_outcomes = [row for row in outcomes if row["quarter"] in evaluated]
    start, end = complete_outcomes[0]["dates"][0], complete_outcomes[-1]["dates"][-1]
    window_count = sum(row["completed_windows"] for row in complete)
    session_count = sum(len(row["dates"]) for row in complete_outcomes)
    return dict(oos_quarters=len(complete), mean_regret=fmean(row["regret"] for row in complete),
                start_date=start, end_date=end,
                total_return_pct=(math.prod(1 + row["net_return_pct"] / 100 for row in complete) - 1) * 100,
                spy_total_return_pct=100 * (benchmark.values[end] / benchmark.values[start] - 1),
                win_rate_pct=100 * fmean(row["net_return_pct"] > 0 for row in complete),
                beat_spy_rate_pct=100 * fmean(row["net_return_pct"] > row["spy_return_pct"] for row in complete),
                worst_quarter_return_pct=min(row["net_return_pct"] for row in complete),
                cash_quarter_rate_pct=100 * fmean(row["selected_strategy"] == "CASH" for row in complete),
                trade_count=sum(row["trade_count"] for row in complete),
                active_window_rate_pct=100 * sum(row["active_windows"] for row in complete) / window_count,
                exposure_rate_pct=100 * sum(row["holding_bars"] for row in complete) / session_count,
                family_comparisons=[_family_comparison(complete_outcomes, family) for family in FAMILY_KEYS],
                strategy_switches=sum(left["selected_strategy"] != right["selected_strategy"]
                                      for left, right in zip(complete, complete[1:])))


def run_macro_router(bars, *, symbol, benchmark=None, price_basis=None,
                     economic_config=None, cost_pct_per_side=DEFAULT_COST_PCT_PER_SIDE,
                     provider=None, as_of: date | None = None):
    """Build a separately versioned optional Auto Tune report.

    Existing A–F global train/validation/test fits never become router labels.
    The inner technical tuner and macro model both use historical prefixes.
    Current-quarter routes are persisted and reused in later-quarter reports.
    Earlier unrecorded selections are identified as retrospective walk-forward.
    """
    if not is_us_stock_code(symbol):
        return unavailable_report("MATR currently requires a US stock or ETF")
    if price_basis != "ADJUSTED_TOTAL_RETURN" or benchmark is None:
        return unavailable_report("MATR requires adjusted stock prices and an exactly aligned SPY total-return benchmark")
    live_request = as_of is None
    as_of = as_of or get_market_now("us").date()
    current_quarter = quarter_for_date(as_of)
    economic_config = economic_config or EconomicConfig()
    try:
        provider = provider or MacroDataProvider.from_config()
        if live_request:
            try:
                completed = get_effective_trading_date("us", strict=True).isoformat()
            except (RuntimeError, ValueError):
                raise MacroDataUnavailable("NYSE completed-session calendar unavailable") from None
            bars = [bar for bar in bars if str(bar["date"]) <= completed]
        engine = MacroExecutionEngine(bars, benchmark=benchmark, economic_config=economic_config,
                                      cost_pct_per_side=cost_pct_per_side, as_of=as_of)
        # Resolve optional data before the expensive nested technical search.
        # The prepared calendar windows already determine the required quarters.
        quarters = list(dict.fromkeys([current_quarter] + [window["quarter"] for window in engine.windows]))
        snapshots = provider.get_snapshots(quarters)
        outcomes = engine.quarterly_outcomes()
        current_snapshot = snapshots[current_quarter]
        scope = _scope(symbol, economic_config, cost_pct_per_side)
        training, history, equity_dates, equity_values, decisions = [], [], [], [], []
        nav = 1.

        def append_performance(outcome, selection):
            nonlocal nav
            history.append(_quarter_report(outcome, selection))
            family = outcome["families"][selection["selected_strategy"]]
            equity_dates.extend(outcome["dates"])
            equity_values.extend((nav * value - 1) * 100 for value in family["equity"])
            nav *= family["equity"][-1]
            for window in family["windows"]:
                decisions.extend(window["decisions"])

        for outcome in outcomes:
            quarter = outcome["quarter"]
            if quarter >= current_quarter or not outcome["complete"]:
                continue
            snapshot = snapshots[quarter]
            selection = _decision(training, snapshot, provider.cache_dir, scope, freeze=False)
            if selection["available"]:
                append_performance(outcome, selection)
            training.append(dict(quarter=quarter, features=snapshot.features,
                                 utilities={key: outcome["families"][key]["utility"] for key in FAMILY_KEYS}))
        current = _decision(training, current_snapshot, provider.cache_dir, scope, freeze=True)
        # The technical parameters may change at the next window; the route above
        # remains the authoritative persisted choice for this quarter and scope.
        current["parameters"] = engine.parameters_for(current["selected_strategy"])
        current["window_start"] = engine.current_window_start
        current_performance_unavailable = False
        for outcome in outcomes:
            if outcome["quarter"] == current_quarter and current["available"]:
                if "SPY_BuyHold" in outcome["families"]:
                    append_performance(outcome, current)
                else:
                    current_performance_unavailable = True
        warnings = [
            "MATR uses its own quarter-grouped nested walk-forward; the A–F test-year split does not apply.",
            "ALFRED availability dates have daily precision; intraday publication timing is not modeled.",
            "Current quarter regime is a quarter-start estimate; routing is frozen until the next quarter.",
        ]
        if current_snapshot.missing_features:
            warnings.append("Missing vintage features: " + ", ".join(current_snapshot.missing_features))
        if current_performance_unavailable:
            warnings.append("Current-quarter performance unavailable: incomplete SPY benchmark dates; the frozen forecast is retained.")
        # One continuous buy-and-hold benchmark captures overnight moves at
        # quarter boundaries; compounding quarter-local curves drops them.
        spy_values = [(benchmark.values[day] / benchmark.values[equity_dates[0]] - 1) * 100
                      for day in equity_dates]
        return dict(strategy_key="MATR", version=ROUTER_VERSION,
                    status="READY" if current["available"] else "INSUFFICIENT_HISTORY",
                    reason=current["reason"], current=current, correlations=current["correlations"],
                    history=history, diagnostics=_diagnostics(history, outcomes, benchmark), warnings=warnings,
                    test_equity=dict(dates=equity_dates, values=equity_values), test_decisions=decisions,
                    benchmark_equity=dict(dates=equity_dates, values=spy_values),
                    test_prices=dict(dates=equity_dates, values=[
                        engine.base["close"][engine.dates.index(day)] for day in equity_dates]),
                    target_cagr=economic_config.target_cagr,
                    assumptions=dict(window_bars=WINDOW_BARS, max_buys=1, max_sells=1,
                                     exit="force_close_at_window_end", execution="next_open",
                                     cost_pct_per_side=cost_pct_per_side, candidate_families=list(FAMILY_KEYS),
                                     target_cagr=economic_config.target_cagr,
                                     cash_utility=0., benchmark="SPY total return",
                                     independent_macro_samples="completed_quarters"))
    except (MacroDataError, MacroExecutionUnavailable) as error:
        return unavailable_report(str(error))
