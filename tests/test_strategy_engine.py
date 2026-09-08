# -*- coding: utf-8 -*-
"""Parity tests for the shared StrategyEngine (Phase 2).

The same fixed OHLCV fixture runs through three legs:

1. ``strategy_engine.evaluate`` (live-signal evaluation entry)
2. backtest signal path (``prepare_base_series`` + ``compute_composite_signals``)
3. live/chart path (``indicator_service.compute_indicators`` composite)

For every date the action, scores, thresholds and factor values must be
identical. All three legs share one scoring formula
(``strategy_scoring.score_bar`` / ``signal_enter``).
"""

import math
from datetime import date, timedelta

import pytest

from src.services.indicator_service import DEFAULT_THRESHOLDS, compute_indicators
from src.services.strategy_backtester import (
    compute_composite_signals,
    prepare_base_series,
    simulate_trades,
)
from src.services.strategy_engine import (
    evaluate,
    evaluate_signals,
    generation_flags,
    resolve_thresholds,
)
from src.services.strategy_scoring import signal_enter


def _synthetic_closes(n):
    return [
        round(
            100.0 + 0.02 * i
            + 6.0 * math.sin(i / 18.0)
            + 2.0 * math.sin(i / 7.0),
            4,
        )
        for i in range(n)
    ]


def _make_bars(closes, start=date(2020, 1, 1)):
    bars = []
    current = start
    for close in closes:
        bars.append(
            {
                "date": current.isoformat(),
                "open": float(close),
                "high": float(close) + 0.06,
                "low": float(close) - 0.06,
                "close": float(close),
                "volume": 1_000_000.0,
            }
        )
        current += timedelta(days=1)
    return bars


FIXTURE_BARS = _make_bars(_synthetic_closes(400))

CUSTOM_PARAMS = {
    "composite_buy_threshold": 5,
    "composite_sell_threshold": 5,
    "rsi_low": 25,
    "rsi_high": 75,
    "kdj_low": 30,
    "kdj_high": 80,
    "macd_lookback": 60,
    "macd_low_percentile": 10,
    "macd_high_percentile": 90,
    "trend_period": 50,
}


def _expected_action(decision_index, backtest_signals, evaluation):
    """Ungated signal presence from the backtest leg (strategy A has no gates)."""
    if backtest_signals["sell_signal"][decision_index] is not None:
        return "SELL"
    if backtest_signals["buy_signal"][decision_index] is not None:
        return "BUY"
    return "HOLD"


@pytest.mark.parametrize("params", [None, CUSTOM_PARAMS])
@pytest.mark.parametrize("strategy", ["A", "F"])
def test_engine_backtest_chart_parity_per_date(params, strategy):
    evaluation = evaluate(FIXTURE_BARS, strategy=strategy, parameters=params)
    decisions = evaluation["decisions"]
    assert len(decisions) == len(FIXTURE_BARS)

    base = prepare_base_series(FIXTURE_BARS)
    backtest_signals = compute_composite_signals(base, params)
    computed = compute_indicators(FIXTURE_BARS, params)
    composite = computed["composite"]

    th = resolve_thresholds(params)
    buy_th = int(th["composite_buy_threshold"])
    sell_th = int(th["composite_sell_threshold"])
    assert any(
        v is not None for v in backtest_signals["buy_signal"]
    ) or any(v is not None for v in backtest_signals["sell_signal"]), (
        "fixture must fire signals"
    )

    for i, decision in enumerate(decisions):
        # Scores identical across all three legs.
        assert decision.buy_score == backtest_signals["buy_score"][i]
        assert decision.sell_score == backtest_signals["sell_score"][i]
        assert decision.buy_score == composite["buy_score"][i]
        assert decision.sell_score == composite["sell_score"][i]
        # Thresholds identical.
        assert decision.buy_threshold == buy_th
        assert decision.sell_threshold == sell_th
        # Factor values identical to the chart breakdowns.
        assert decision.buy_breakdown == composite["buy_breakdown"][i]
        assert decision.sell_breakdown == composite["sell_breakdown"][i]
        if decision.action == "BUY":
            assert decision.factors == composite["buy_breakdown"][i]
        elif decision.action == "SELL":
            assert decision.factors == composite["sell_breakdown"][i]
        # Signal presence identical.
        assert (backtest_signals["buy_signal"][i] is not None) == (
            composite["buy_signal"][i] is not None
        )
        assert (backtest_signals["sell_signal"][i] is not None) == (
            composite["sell_signal"][i] is not None
        )
        # Action follows the shared enter rule plus generation gates.
        if strategy == "A":
            assert decision.action == _expected_action(i, backtest_signals, evaluation)
        else:
            # Gated strategy: every BUY is a real backtest signal with gates passing;
            # every gated-out signal is HOLD with the gate state recorded.
            if decision.action == "BUY":
                assert backtest_signals["buy_signal"][i] is not None
                assert decision.filters["trend_gate"] is True
                assert decision.filters["volume_gate"] is True
            if decision.action == "SELL":
                assert backtest_signals["sell_signal"][i] is not None
            if (
                backtest_signals["buy_signal"][i] is not None
                and decision.action == "HOLD"
            ):
                assert (
                    decision.filters["trend_gate"] is False
                    or decision.filters["volume_gate"] is False
                )


def test_backtester_executes_engine_signals_next_open():
    # Strategy A has no gates: every engine BUY must fill at the next open.
    evaluation = evaluate(FIXTURE_BARS, strategy="A")
    base = prepare_base_series(FIXTURE_BARS)
    signals = compute_composite_signals(base, None)
    simulation = simulate_trades(
        base, signals, 0, len(FIXTURE_BARS) - 1,
        window_days=1, cost_pct_per_side=0.0,
    )
    buy_dates = {
        d.date for d in evaluation["decisions"] if d.action == "BUY"
    }
    sell_dates = {
        d.date for d in evaluation["decisions"] if d.action == "SELL"
    }
    assert buy_dates, "fixture must contain BUY decisions"
    fills = {(t["entry_date"], t["exit_date"]) for t in simulation["trades"]}
    assert fills, "backtester must execute the shared signals"
    dates = [b["date"] for b in FIXTURE_BARS]
    for entry_date, exit_date in fills:
        # Entry fill is the bar after a BUY decision (next-open execution).
        assert dates[dates.index(entry_date) - 1] in buy_dates
        # Exit fill is the bar after a SELL decision.
        assert dates[dates.index(exit_date) - 1] in sell_dates


def test_evaluate_is_deterministic_and_reproducible():
    first = evaluate(FIXTURE_BARS, strategy="D", parameters=CUSTOM_PARAMS)
    second = evaluate(FIXTURE_BARS, strategy="D", parameters=CUSTOM_PARAMS)
    assert [(d.date, d.action, d.buy_score, d.sell_score) for d in first["decisions"]] == [
        (d.date, d.action, d.buy_score, d.sell_score) for d in second["decisions"]
    ]
    assert first["thresholds"] == second["thresholds"]


def test_signal_enter_suppresses_ambiguous_bars():
    assert signal_enter(0, 6, 0, 5, 6, 6) == (True, False)
    assert signal_enter(0, 5, 0, 6, 6, 6) == (False, True)
    # Both sides entering on the same bar: no signal either way.
    assert signal_enter(0, 7, 0, 7, 6, 6) == (False, False)
    # Already inside the band: no re-trigger.
    assert signal_enter(6, 7, 0, 3, 6, 6) == (False, False)


def test_generation_flags_and_threshold_resolution():
    assert generation_flags("A") == {
        "trend_filter": False, "volume_filter": False, "atr_risk": False,
    }
    assert generation_flags("F")["trend_filter"] is True
    with pytest.raises(ValueError):
        generation_flags("Z")
    resolved = resolve_thresholds({"composite_buy_threshold": 5, "no_such_key": 1})
    assert resolved["composite_buy_threshold"] == 5.0
    assert "no_such_key" not in resolved
    assert resolved["composite_sell_threshold"] == DEFAULT_THRESHOLDS["composite_sell_threshold"]


def test_evaluate_signals_exposes_breakdowns_for_charts():
    base = prepare_base_series(FIXTURE_BARS)
    signals = evaluate_signals(base, CUSTOM_PARAMS)
    assert set(signals) == {
        "buy_score", "sell_score", "buy_breakdown",
        "sell_breakdown", "buy_signal", "sell_signal",
    }
    assert len(signals["buy_breakdown"]) == len(FIXTURE_BARS)
