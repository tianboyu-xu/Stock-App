# -*- coding: utf-8 -*-
"""Deterministic tests for the Auto Tune strategy backtester."""

import json
import math
from datetime import date, timedelta

import pytest

from src.services.indicator_optimizer import (
    MAX_TEST_USABLE_RATIO,
    MIN_TRAINVAL_BARS,
    MIN_TRAIN_BARS,
    TRAIN_RATIO,
    TRADING_DAYS_PER_YEAR,
    TUNABLE_GRID,
    VALIDATION_RATIO,
    WARMUP_BARS,
    _build_benchmarks,
    _clip_train_range,
    _split_ranges,
    calculate_trigger_benefits,
    run_auto_tune,
)
from src.services.indicator_service import DEFAULT_THRESHOLDS, compute_indicators
from src.services.strategy_backtester import (
    DEFAULT_LONG_TERM_TAX_PCT,
    DEFAULT_SHORT_TERM_TAX_PCT,
    LONG_TERM_HOLDING_BARS,
    compute_composite_signals,
    objective_score,
    prepare_base_series,
    simulate_buy_hold,
    simulate_trades,
    summarize_metrics,
    timing_signals_from_trades,
)


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


def _flat_bars(n, price=10.0):
    # Constant close with a fixed high/low range keeps ATR deterministic.
    bars = []
    current = date(2020, 1, 1)
    for _ in range(n):
        bars.append(
            {
                "date": current.isoformat(),
                "open": price,
                "high": price + 0.06,
                "low": price - 0.06,
                "close": price,
                "volume": 1_000_000.0,
            }
        )
        current += timedelta(days=1)
    return bars


def _manual_signals(n, buys=(), sells=(), price=10.0):
    buy = [None] * n
    sell = [None] * n
    for i in buys:
        buy[i] = price
    for i in sells:
        sell[i] = price
    return {"buy_signal": buy, "sell_signal": sell}


def test_budget_cash_position_and_weighted_profit():
    base = prepare_base_series(_make_bars([10, 10, 12, 12, 12, 12]))
    signals = _manual_signals(6, buys=(0, 1), sells=(2, 4))
    signals["buy_allocation"] = [0.5] * 6
    sim = simulate_trades(base, signals, 0, 5, window_days=1,
                          cost_pct_per_side=0, size_by_score=True)
    assert sim["equity"] == pytest.approx([1, 1, 1.1, 1.1, 1.1, 1.1])
    assert sim["trades"][0]["allocation_pct"] == 50
    assert [(d["side"], d["reason"]) for d in sim["decisions"]] == [
        ("buy", "signal"), ("buy", "position_open"), ("sell", "signal"), ("sell", "no_position")]
    assert sim["decisions"][0]["cash_after_pct"] == 50
    assert sim["decisions"][2]["executed_budget_pct"] == pytest.approx(60)
    metrics = summarize_metrics(sim, 0, 5, short_term_tax_pct=35)
    assert metrics["total_return_pct"] == 10
    assert metrics["after_tax_total_return_pct"] == 6.5


def test_chart_execution_fields_use_fill_nav_and_signal_score():
    base = prepare_base_series(_make_bars([10, 10, 12, 12, 12, 12]))
    signals = _manual_signals(6, buys=(0, 1), sells=(2,))
    signals.update(buy_allocation=[.5] * 6, buy_score=[7] * 6, sell_score=[-6] * 6)
    sim = simulate_trades(base, signals, 0, 5, window_days=1, cost_pct_per_side=.1, size_by_score=True)
    buy, blocked, sell = sim["decisions"]
    assert buy["execution_price"] == 10
    assert buy["score"] == 7
    assert buy["trade_nav_pct"] == pytest.approx(50 / 1.001)
    assert 49 < buy["holding_pct"] < 50
    assert blocked["status"] == "skipped"
    assert "execution_price" not in blocked
    assert sell["execution_price"] == 12
    assert sell["holding_pct"] == 0
    assert sell["score"] == -6
    assert sell["trade_nav_pct"] > 50  # Appreciated stock is over half of current NAV.


def test_exhausted_budget_blocks_buy_and_sale_replenishes_cash():
    base = prepare_base_series(_flat_bars(9))
    signals = _manual_signals(9, buys=(0, 2, 6), sells=(4,))
    sim = simulate_trades(base, signals, 0, 8, window_days=1, cost_pct_per_side=0.1,
                          size_by_score=True)
    assert sim["decisions"][1]["reason"] == "no_cash"
    assert sim["decisions"][1]["executed_budget_pct"] == 0
    assert sim["decisions"][3]["status"] == "executed"
    assert all(d["cash_after_pct"] >= 0 for d in sim["decisions"])
    assert sim["equity"][-1] == pytest.approx(((1 - .001) / (1 + .001)) ** 2)


def test_trade_cooldown_includes_exits_and_reentry_but_not_stops():
    base = prepare_base_series(_flat_bars(15))
    signals = _manual_signals(15, buys=(0, 7, 10), sells=(1, 5))
    sim = simulate_trades(base, signals, 0, 14, window_days=1, cost_pct_per_side=0,
                          min_trade_gap_bars=5)
    assert [d["reason"] for d in sim["decisions"]][:5] == [
        "signal", "trade_cooldown", "signal", "trade_cooldown", "signal"]
    assert sim["trades"][0]["bars_held"] == 5
    base["atr"] = [1.0] * 15
    base["low"][2] = 8.0
    protected = simulate_trades(base, signals, 0, 14, window_days=1, cost_pct_per_side=0,
                                min_trade_gap_bars=5, stop_multiple_atr=1)
    assert protected["trades"][0]["exit_reason"] == "stop"
    assert protected["trades"][0]["bars_held"] == 1


def test_multifactor_allocation_uses_theoretical_maximum_without_lookahead():
    base = prepare_base_series(_make_bars(_synthetic_closes(300)))
    signals = compute_composite_signals(base)
    assert signals["buy_allocation"] == [max(.25, score / 10) for score in signals["buy_score"]]
    extra = compute_composite_signals(base, {"boll_weight": 2, "cci_weight": 1})
    assert extra["buy_allocation"] == [max(.25, score / 13) for score in extra["buy_score"]]
    prefix = prepare_base_series(_make_bars(_synthetic_closes(250)))
    prefix_signals = compute_composite_signals(prefix, {"boll_weight": 2, "cci_weight": 1})
    assert extra["buy_allocation"][:250] == prefix_signals["buy_allocation"]


def test_timing_benchmark_replays_allocation_as_well_as_dates():
    base = prepare_base_series(_make_bars([10, 10, 12, 12, 12]))
    signals = timing_signals_from_trades(
        base, [(base["dates"][1], base["dates"][3])], allocations=[.5])
    sim = simulate_trades(base, signals, 0, 4, window_days=1, cost_pct_per_side=0,
                          size_by_score=True)
    assert sim["equity"][-1] == pytest.approx(1.1)
    assert sim["trades"][0]["allocation_pct"] == 50


def test_budget_profit_factor_weights_actual_cash_gains_and_losses():
    base = prepare_base_series(_make_bars([10, 10, 12, 12, 10, 9, 9]))
    signals = _manual_signals(7, buys=(0, 3), sells=(2, 5))
    signals["buy_allocation"] = [.5, .5, .5, 1, 1, 1, 1]
    sim = simulate_trades(base, signals, 0, 6, window_days=1, cost_pct_per_side=0,
                          size_by_score=True)
    metrics = summarize_metrics(sim, 0, 6)
    assert metrics["total_return_pct"] == -1
    assert metrics["profit_factor"] == round(.1 / .11, 4)


CUSTOM_THRESHOLDS = {
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


def _assert_signals_match(expected, actual):
    assert len(expected) == len(actual)
    for a, b in zip(expected, actual):
        assert (a is None) == (b is None)
        if a is not None:
            assert abs(a - b) < 1e-9


def test_composite_signals_match_indicator_service_defaults():
    bars = _make_bars(_synthetic_closes(250))
    computed = compute_indicators(bars)
    signals = compute_composite_signals(prepare_base_series(bars))
    _assert_signals_match(computed["composite"]["buy_signal"], signals["buy_signal"])
    _assert_signals_match(computed["composite"]["sell_signal"], signals["sell_signal"])


def test_composite_signals_match_indicator_service_custom_thresholds():
    bars = _make_bars(_synthetic_closes(250))
    computed = compute_indicators(bars, CUSTOM_THRESHOLDS)
    signals = compute_composite_signals(prepare_base_series(bars), CUSTOM_THRESHOLDS)
    _assert_signals_match(computed["composite"]["buy_signal"], signals["buy_signal"])
    _assert_signals_match(computed["composite"]["sell_signal"], signals["sell_signal"])


def test_lower_buy_threshold_never_reduces_buy_signals():
    bars = _make_bars(_synthetic_closes(400))
    base = prepare_base_series(bars)
    strict = compute_composite_signals(base, {"composite_buy_threshold": 9})
    loose = compute_composite_signals(base, {"composite_buy_threshold": 3})
    strict_count = sum(1 for v in strict["buy_signal"] if v is not None)
    loose_count = sum(1 for v in loose["buy_signal"] if v is not None)
    assert loose_count >= strict_count


def test_entry_and_exit_execute_next_open():
    bars = _flat_bars(30)
    base = prepare_base_series(bars)
    signals = _manual_signals(len(bars), buys=(5,), sells=(10,))
    sim = simulate_trades(
        base, signals, 0, len(bars) - 1, window_days=1, cost_pct_per_side=0.0,
    )
    assert len(sim["trades"]) == 1
    trade = sim["trades"][0]
    # Signal confirmed at close of bar 5 -> filled at open of bar 6.
    assert trade["entry_date"] == bars[6]["date"]
    assert abs(trade["entry_price"] - bars[6]["open"]) < 1e-9
    assert trade["exit_date"] == bars[11]["date"]
    assert abs(trade["exit_price"] - bars[11]["open"]) < 1e-9
    assert trade["exit_reason"] == "signal"
    assert trade["bars_held"] == 5


def test_window_gap_limits_entry_frequency():
    bars = _flat_bars(300)
    base = prepare_base_series(bars)
    n = len(bars)
    signals = _manual_signals(n, buys=(0, 100, 200), sells=(50, 150, 250))
    sim90 = simulate_trades(
        base, signals, 0, n - 1, window_days=90, cost_pct_per_side=0.0,
    )
    sim150 = simulate_trades(
        base, signals, 0, n - 1, window_days=150, cost_pct_per_side=0.0,
    )
    assert len(sim90["trades"]) == 3
    assert len(sim150["trades"]) == 2
    entries = [
        date.fromisoformat(trade["entry_date"]) for trade in sim90["trades"]
    ]
    for prev, curr in zip(entries, entries[1:]):
        assert (curr - prev).days >= 90


def test_atr_stop_exits_at_stop_level():
    bars = _flat_bars(40)
    base = prepare_base_series(bars)
    signals = _manual_signals(len(bars), buys=(20,))
    # Crash bar: open above the stop level, low far below it.
    crash = 23
    bars[crash]["open"] = 9.97
    bars[crash]["high"] = 10.06
    bars[crash]["low"] = 5.0
    bars[crash]["close"] = 5.05
    base = prepare_base_series(bars)
    sim = simulate_trades(
        base, signals, 0, len(bars) - 1, window_days=1, cost_pct_per_side=0.0,
        stop_multiple_atr=1.0,
    )
    assert len(sim["trades"]) == 1
    trade = sim["trades"][0]
    assert trade["exit_reason"] == "stop"
    # ATR is exactly 0.12 on this series -> stop = entry(10.0) - 1.0 * 0.12.
    assert abs(trade["exit_price"] - 9.88) < 1e-6
    assert trade["return_pct"] < 0


@pytest.mark.parametrize("cost_pct", [0.0, 1.0])
@pytest.mark.parametrize("exit_reason", ["signal", "stop", "trail", "segment_end"])
def test_exit_paths_charge_each_side_once_and_reconcile_equity(cost_pct, exit_reason):
    bars = _flat_bars(25)
    sells = (22,) if exit_reason == "signal" else ()
    if exit_reason == "signal":
        bars[23].update(open=11.0, high=11.06, low=10.0, close=11.0)
    elif exit_reason in {"stop", "trail"}:
        bars[23].update(low=8.0, close=9.0)
    else:
        bars[24].update(high=11.06, close=11.0)
    cost = cost_pct / 100.0
    entry = 10.0 * (1.0 + cost)
    raw_exit = {
        "signal": 11.0,
        "stop": entry - 3.0 * 0.12,
        "trail": 10.0 - 3.0 * 0.12,
        "segment_end": 11.0,
    }[exit_reason]
    simulation = simulate_trades(
        prepare_base_series(bars), _manual_signals(len(bars), buys=(20,), sells=sells),
        0, len(bars) - 1, window_days=1, cost_pct_per_side=cost_pct,
        stop_multiple_atr=3.0 if exit_reason == "stop" else None,
        trail_multiple_atr=3.0 if exit_reason == "trail" else None,
    )
    trade, = simulation["trades"]
    expected_equity = raw_exit * (1.0 - cost) / entry
    assert trade["exit_reason"] == exit_reason
    assert trade["entry_price"] == pytest.approx(entry)
    assert trade["exit_price"] == pytest.approx(raw_exit * (1.0 - cost), abs=1e-4)
    assert trade["return_pct"] == pytest.approx((expected_equity - 1.0) * 100.0, abs=1e-4)
    assert simulation["equity"][-1] == pytest.approx(expected_equity)
    assert simulation["initial_equity"] == 1.0
    metrics = summarize_metrics(simulation, 0, len(bars) - 1, 0.0, 0.0)
    assert metrics["total_return_pct"] == trade["return_pct"]
    assert metrics["after_tax_total_return_pct"] == trade["return_pct"]
    expected_holding = {"signal": 2, "stop": 3, "trail": 3, "segment_end": 4}[exit_reason]
    assert simulation["holding_bars"] == expected_holding


@pytest.mark.parametrize("exit_reason", ["stop", "trail"])
def test_gap_through_exit_level_fills_at_open_with_one_exit_fee(exit_reason):
    bars = _flat_bars(25)
    bars[23].update(open=9.0, high=9.1, low=8.9, close=9.0)
    simulation = simulate_trades(
        prepare_base_series(bars), _manual_signals(len(bars), buys=(20,)),
        0, len(bars) - 1, window_days=1, cost_pct_per_side=0.1,
        stop_multiple_atr=1.0 if exit_reason == "stop" else None,
        trail_multiple_atr=1.0 if exit_reason == "trail" else None,
    )
    trade, = simulation["trades"]
    assert trade["exit_reason"] == exit_reason
    assert trade["exit_date"] == bars[23]["date"]
    assert trade["exit_price"] == pytest.approx(9.0 * 0.999)
    assert simulation["equity"][-1] == pytest.approx(9.0 * 0.999 / (10.0 * 1.001))
    assert simulation["holding_bars"] == 2  # Entry day + next day; gap exits at the open.


def test_atr_stop_uses_only_information_available_before_entry_open():
    bars = _flat_bars(25)
    # The entry-day high is unknown at entry and must not widen the fixed stop.
    bars[21].update(high=15.0, low=9.99)
    bars[22].update(low=9.8, close=9.9)
    base = prepare_base_series(bars)
    assert base["atr"][21] > base["atr"][20]
    simulation = simulate_trades(
        base, _manual_signals(len(bars), buys=(20,)), 0, len(bars) - 1,
        window_days=1, cost_pct_per_side=0.0, stop_multiple_atr=1.0,
    )
    trade, = simulation["trades"]
    assert trade["exit_date"] == bars[22]["date"]
    assert trade["exit_reason"] == "stop"
    assert trade["exit_price"] == pytest.approx(9.88)


def test_initial_stop_protects_entry_day_and_counts_intraday_exposure():
    bars = _flat_bars(25)
    bars[21].update(low=9.0, close=9.5)
    simulation = simulate_trades(
        prepare_base_series(bars), _manual_signals(len(bars), buys=(20,)),
        0, len(bars) - 1, window_days=1, cost_pct_per_side=0.0, stop_multiple_atr=1.0,
    )
    trade, = simulation["trades"]
    assert trade["entry_date"] == trade["exit_date"] == bars[21]["date"]
    assert trade["exit_reason"] == "stop"
    assert trade["exit_price"] == pytest.approx(9.88)
    assert trade["bars_held"] == 0
    assert simulation["holding_bars"] == 1
    assert simulation["equity"][21] == pytest.approx(0.988)


def test_trailing_stop_uses_prior_close_and_precedes_lower_fixed_stop():
    bars = _flat_bars(25)
    # Entry-day low precedes a close-based trailing level becoming active.
    bars[21].update(high=12.1, low=9.95, close=12.0)
    bars[22].update(open=12.0, high=12.1, low=9.0, close=9.5)
    simulation = simulate_trades(
        prepare_base_series(bars), _manual_signals(len(bars), buys=(20,)),
        0, len(bars) - 1, window_days=1, cost_pct_per_side=0.0,
        stop_multiple_atr=3.0, trail_multiple_atr=3.0,
    )
    trade, = simulation["trades"]
    assert trade["exit_date"] == bars[22]["date"]
    assert trade["exit_reason"] == "trail"
    assert trade["exit_price"] == pytest.approx(12.0 - 3.0 * 0.12)


def test_exposure_accumulates_across_closed_and_terminal_trades():
    bars = _flat_bars(15)
    simulation = simulate_trades(
        prepare_base_series(bars), _manual_signals(len(bars), buys=(1, 7, 12), sells=(4, 9)),
        0, len(bars) - 1, window_days=1, cost_pct_per_side=0.1,
    )
    assert len(simulation["trades"]) == 3
    assert simulation["holding_bars"] == 3 + 2 + 2
    assert simulation["equity"][-1] == pytest.approx((0.999 / 1.001) ** 3)
    metrics = summarize_metrics(simulation, 0, len(bars) - 1)
    assert metrics["exposure_pct"] == pytest.approx(7 / 15 * 100.0, abs=1e-4)


def test_objective_score_penalizes_too_few_trades_and_drawdown():
    base_metrics = {
        "total_return_pct": 30.0,
        "cagr_pct": 10.0,
        "max_drawdown_pct": -10.0,
        "sharpe": 1.0,
        "sortino": 1.2,
        "profit_factor": 1.8,
        "trades": 20,
        "win_rate_pct": 55.0,
        "avg_trade_pct": 1.5,
        "avg_holding_days": 15.0,
        "exposure_pct": 40.0,
        "trades_per_year": 4.0,
    }
    few_trades = dict(base_metrics, trades=1)
    assert objective_score(few_trades, 5.0) < -1.0e5
    deep_drawdown = dict(base_metrics, max_drawdown_pct=-40.0)
    assert objective_score(base_metrics, 5.0) > objective_score(deep_drawdown, 5.0)


def test_run_auto_tune_returns_six_generations_and_is_deterministic():
    bars = _make_bars(_synthetic_closes(760))
    report = run_auto_tune(bars, window_days=90, history_years=10)
    assert [s["key"] for s in report["strategies"]] == ["A", "B", "C", "D", "E", "F"]

    recommended = report["recommended"]
    assert recommended["strategy_key"] in {"A", "B", "C", "D", "E", "F"}
    for key in (
        "composite_buy_threshold",
        "composite_sell_threshold",
        "rsi_low",
        "rsi_high",
        "kdj_low",
        "kdj_high",
        "macd_lookback",
        "macd_low_percentile",
        "macd_high_percentile",
        "trend_period",
    ):
        assert key in recommended["thresholds"]

    segments = {"train", "validation", "test", "train_validation"}
    extra_weight_keys = (
        "boll_weight",
        "cci_weight",
        "dmi_weight",
        "mfi_weight",
        "volume_weight",
        "range52_weight",
    )
    for strategy in report["strategies"]:
        assert segments <= set(strategy["metrics"].keys())
        assert segments <= set(strategy["objectives"].keys())
        if strategy["tuned"]:
            for key, value in strategy["params"]["thresholds"].items():
                assert value in TUNABLE_GRID[key]
        if strategy["key"] in {"A", "B", "C", "D"}:
            # 经典代际只调经典参数：扩展因子权重恒为默认 0（信号与改动前一致）
            for key in extra_weight_keys:
                assert strategy["params"]["thresholds"][key] == 0
        else:
            assert strategy["key"] in {"E", "F"}

    assert report["split"]["train"]["bars"] > 0
    assert report["split"]["validation"]["bars"] > 0
    assert report["split"]["test"]["bars"] > 0

    again = run_auto_tune(bars, window_days=90, history_years=10)
    assert json.dumps(report, sort_keys=True) == json.dumps(again, sort_keys=True)


def test_run_auto_tune_rejects_insufficient_history():
    bars = _make_bars(_synthetic_closes(100))
    with pytest.raises(ValueError):
        run_auto_tune(bars, window_days=90, history_years=10)


def test_split_ranges_legacy_path_keeps_ratio_split():
    n = 1100
    ranges = _split_ranges(n)
    usable = n - WARMUP_BARS
    train_len = int(usable * TRAIN_RATIO)
    validation_len = int(usable * VALIDATION_RATIO)
    assert ranges["train"] == (WARMUP_BARS, WARMUP_BARS + train_len - 1)
    assert ranges["validation"] == (
        WARMUP_BARS + train_len,
        WARMUP_BARS + train_len + validation_len - 1,
    )
    assert ranges["test"] == (WARMUP_BARS + train_len + validation_len, n - 1)


def test_split_ranges_with_explicit_test_bars_reserves_tail_segment():
    n = 2600
    requested = round(5 * TRADING_DAYS_PER_YEAR)
    ranges = _split_ranges(n, test_bars=requested)
    usable = n - WARMUP_BARS
    remaining = usable - requested
    train_len = int(remaining * TRAIN_RATIO / (TRAIN_RATIO + VALIDATION_RATIO))
    assert ranges["test"][0] == n - requested
    assert ranges["validation"][1] == ranges["test"][0] - 1
    assert ranges["train"] == (WARMUP_BARS, WARMUP_BARS + train_len - 1)
    assert ranges["train_validation"] == (ranges["train"][0], ranges["validation"][1])


def test_split_ranges_clamps_excessive_test_bars():
    n = 1000
    ranges = _split_ranges(n, test_bars=10_000)
    usable = n - WARMUP_BARS
    max_test = min(int(usable * MAX_TEST_USABLE_RATIO), usable - MIN_TRAINVAL_BARS)
    assert ranges["test"][1] - ranges["test"][0] + 1 == max_test
    # 训练+验证段必须保留最小规模
    assert ranges["train_validation"][1] - ranges["train_validation"][0] + 1 >= MIN_TRAINVAL_BARS


def _clip_dates(count):
    base = date(2005, 1, 3)
    return [(base + timedelta(days=i)).isoformat() for i in range(count)]


def test_clip_train_range_limits_to_selected_dates():
    ranges = _split_ranges(2600, test_bars=round(5 * TRADING_DAYS_PER_YEAR))
    dates = _clip_dates(2600)
    lo, hi = ranges["train"]
    assert _clip_train_range(ranges, dates, None, None) == (lo, hi)

    mid_start = lo + 100
    mid_end = hi - 150
    clipped = _clip_train_range(
        ranges, dates, dates[mid_start], dates[mid_end],
    )
    assert clipped == (mid_start, mid_end)


def test_clip_train_range_swaps_reversed_and_rejects_too_small():
    ranges = _split_ranges(2600, test_bars=round(5 * TRADING_DAYS_PER_YEAR))
    dates = _clip_dates(2600)
    lo, hi = ranges["train"]
    start_idx = lo + 10
    end_idx = lo + 10 + MIN_TRAIN_BARS + 5
    reversed_clip = _clip_train_range(
        ranges, dates, dates[end_idx], dates[start_idx],
    )
    assert reversed_clip == (start_idx, end_idx)

    tiny_end = lo + 20
    with pytest.raises(ValueError):
        _clip_train_range(ranges, dates, dates[lo], dates[tiny_end])


def test_run_auto_tune_honors_test_years_and_train_range():
    bars = _make_bars(_synthetic_closes(1600))
    report = run_auto_tune(bars, window_days=90, history_years=10, test_years=2)
    test_bars = report["split"]["test"]["bars"]
    assert abs(test_bars - round(2 * TRADING_DAYS_PER_YEAR)) <= 2
    assert report["history"]["test_years_requested"] == pytest.approx(2.0)
    assert report["history"]["test_years_used"] == pytest.approx(test_bars / TRADING_DAYS_PER_YEAR, abs=0.05)

    # 裁剪训练段：验证段位置不变，训练段起点后移
    all_dates = [b["date"] for b in bars]
    keep = int(10 * TRADING_DAYS_PER_YEAR)
    kept_dates = all_dates[-keep:]
    ranges = report["split"]
    new_train_start = ranges["train"]["start_date"]
    offset = kept_dates.index(new_train_start)
    shifted_start = kept_dates[offset + 120]
    tuned = run_auto_tune(
        bars,
        window_days=90,
        history_years=10,
        test_years=2,
        train_start_date=shifted_start,
    )
    assert tuned["split"]["train"]["start_date"] == shifted_start
    assert tuned["split"]["validation"]["start_date"] == ranges["validation"]["start_date"]
    assert tuned["split"]["validation"]["end_date"] == ranges["validation"]["end_date"]


def test_default_thresholds_are_inside_tunable_grids():
    for key, grid in TUNABLE_GRID.items():
        assert float(DEFAULT_THRESHOLDS[key]) in [float(v) for v in grid]


def test_summarize_metrics_applies_short_and_long_term_tax():
    trades = [
        {"return_pct": 10.0, "bars_held": 300},  # 长期：15%
        {"return_pct": 10.0, "bars_held": 100},  # 短期：35%
        {"return_pct": -5.0, "bars_held": 50},  # 亏损不计税
    ]
    simulation = {
        "trades": trades,
        "equity": [1.0, 1.09774875],
        "holding_bars": 450,
    }
    metrics = summarize_metrics(simulation, 0, 1)
    expected_mult = (1.0 + 0.10 * (1.0 - 0.15)) * (1.0 + 0.10 * (1.0 - 0.35)) * 0.95
    assert metrics["after_tax_total_return_pct"] == pytest.approx(
        (expected_mult - 1.0) * 100.0, abs=1e-3,
    )

    # 持有恰好满一年（252 个交易日）按长期税率
    boundary = {
        "trades": [{"return_pct": 10.0, "bars_held": LONG_TERM_HOLDING_BARS}],
        "equity": [1.0, 1.085],
        "holding_bars": LONG_TERM_HOLDING_BARS,
    }
    boundary_metrics = summarize_metrics(boundary, 0, 1)
    assert boundary_metrics["after_tax_total_return_pct"] == pytest.approx(8.5, abs=1e-6)

    # 自定义税率覆盖默认值
    custom = summarize_metrics(
        simulation, 0, 1, short_term_tax_pct=40.0, long_term_tax_pct=20.0,
    )
    custom_mult = 1.08 * 1.06 * 0.95
    assert custom["after_tax_total_return_pct"] == pytest.approx(
        (custom_mult - 1.0) * 100.0, abs=1e-3,
    )


def test_simulate_buy_hold_matches_window_prices():
    bars = _make_bars(_synthetic_closes(40))
    base = prepare_base_series(bars)
    sim = simulate_buy_hold(base, 5, 20, cost_pct_per_side=0.0)
    assert len(sim["trades"]) == 1
    trade = sim["trades"][0]
    assert trade["entry_date"] == bars[5]["date"]
    assert trade["exit_date"] == bars[20]["date"]
    assert abs(trade["entry_price"] - bars[5]["open"]) < 1e-9
    assert abs(trade["exit_price"] - bars[20]["close"]) < 1e-9
    expected_return = (bars[20]["close"] / bars[5]["open"] - 1.0) * 100.0
    # return_pct 按 4 位小数四舍五入
    assert trade["return_pct"] == pytest.approx(expected_return, abs=1e-4)
    assert trade["exit_reason"] == "buy_hold"
    assert len(sim["equity"]) == 16
    assert sim["equity"][-1] == pytest.approx(
        bars[20]["close"] / bars[5]["open"], abs=1e-9,
    )


@pytest.mark.parametrize("cost_pct", [0.0, 0.1, 1.0])
def test_buy_hold_and_strategy_share_entry_and_liquidation_accounting(cost_pct):
    bars = _flat_bars(5)
    bars[1].update(high=11.5, close=11.0)
    bars[4].update(high=12.5, close=12.0)
    base = prepare_base_series(bars)
    strategy = simulate_trades(
        base, _manual_signals(len(bars), buys=(0,)), 0, 4,
        window_days=1, cost_pct_per_side=cost_pct,
    )
    buy_hold = simulate_buy_hold(base, 1, 4, cost_pct_per_side=cost_pct)
    assert strategy["equity"][1:] == pytest.approx(buy_hold["equity"])
    for key in ("entry_price", "exit_price", "return_pct", "bars_held"):
        assert strategy["trades"][0][key] == buy_hold["trades"][0][key]
    strategy_metrics = summarize_metrics(strategy, 0, 4)
    buy_hold_metrics = summarize_metrics(buy_hold, 1, 4)
    assert strategy_metrics["total_return_pct"] == buy_hold_metrics["total_return_pct"]
    assert strategy_metrics["max_drawdown_pct"] == buy_hold_metrics["max_drawdown_pct"]
    assert buy_hold_metrics["exposure_pct"] == 100.0


def test_buy_hold_metrics_include_first_bar_return_costs_and_initial_drawdown():
    bars = _make_bars([90.0, 90.0, 99.0])
    bars[0].update(open=100.0, high=100.0)
    simulation = simulate_buy_hold(prepare_base_series(bars), 0, 2, cost_pct_per_side=1.0)
    final_equity = 99.0 * 0.99 / 101.0
    assert simulation["equity"] == pytest.approx([90.0 / 101.0, 90.0 / 101.0, final_equity])
    metrics = summarize_metrics(simulation, 0, 2, 0.0, 0.0)
    assert metrics["total_return_pct"] == pytest.approx((final_equity - 1.0) * 100.0, abs=1e-4)
    assert metrics["cagr_pct"] == pytest.approx((final_equity ** (252 / 3) - 1.0) * 100, abs=1e-4)
    assert metrics["max_drawdown_pct"] == pytest.approx((90.0 / 101.0 - 1.0) * 100.0, abs=1e-4)
    returns = [90.0 / 101.0 - 1.0, 0.0, 99.0 * 0.99 / 90.0 - 1.0]
    mean_r = sum(returns) / 3
    std_r = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / 3)
    down_std = math.sqrt(sum(min(r, 0.0) ** 2 for r in returns) / 3)
    assert metrics["sharpe"] == pytest.approx(mean_r / std_r * math.sqrt(252), abs=1e-4)
    assert metrics["sortino"] == pytest.approx(mean_r / down_std * math.sqrt(252), abs=1e-4)


def test_single_bar_buy_hold_reports_both_costs_and_intraday_return():
    bars = _make_bars([110.0])
    bars[0]["open"] = 100.0
    simulation = simulate_buy_hold(prepare_base_series(bars), 0, 0, cost_pct_per_side=1.0)
    expected = 110.0 * 0.99 / 101.0
    assert simulation["equity"] == pytest.approx([expected])
    assert simulation["holding_bars"] == 1
    assert summarize_metrics(simulation, 0, 0)["total_return_pct"] == pytest.approx(
        (expected - 1.0) * 100.0, abs=1e-4,
    )


def _ramp_bars(n, start_price, step):
    bars = []
    current = date(2020, 1, 1)
    for i in range(n):
        price = start_price + step * i
        bars.append(
            {
                "date": current.isoformat(),
                "open": price,
                "high": price + 0.06,
                "low": price - 0.06,
                "close": price,
                "volume": 1_000_000.0,
            }
        )
        current += timedelta(days=1)
    return bars


def test_timing_signals_replay_trades_on_other_series():
    stock_bars = _ramp_bars(30, 10.0, 0.1)
    sp_bars = _ramp_bars(30, 50.0, 0.05)
    stock_base = prepare_base_series(stock_bars)
    sp_base = prepare_base_series(sp_bars)
    signals = _manual_signals(len(stock_bars), buys=(5,), sells=(10,))
    sim = simulate_trades(
        stock_base, signals, 0, len(stock_bars) - 1,
        window_days=1, cost_pct_per_side=0.0,
    )
    pairs = [(t["entry_date"], t["exit_date"]) for t in sim["trades"]]
    replay_signals = timing_signals_from_trades(sp_base, pairs)
    replayed = simulate_trades(
        sp_base, replay_signals, 0, len(sp_bars) - 1,
        window_days=1, cost_pct_per_side=0.0,
    )
    assert len(replayed["trades"]) == 1
    trade = replayed["trades"][0]
    # 时点与原策略一致，成交价取自标普500 序列（入场/离场均为次日开盘）
    assert trade["entry_date"] == sim["trades"][0]["entry_date"]
    assert trade["exit_date"] == sim["trades"][0]["exit_date"]
    assert abs(trade["entry_price"] - sp_bars[6]["open"]) < 1e-9
    assert abs(trade["exit_price"] - sp_bars[11]["open"]) < 1e-9


def test_run_auto_tune_includes_benchmarks_and_after_tax_metrics():
    bars = _make_bars(_synthetic_closes(760))
    first_close = bars[0]["close"]
    bench_closes = [
        round(first_close + (close - first_close) * 0.8, 4) for close in _synthetic_closes(760)
    ]
    bench_bars = _make_bars(bench_closes)

    report = run_auto_tune(
        bars, window_days=90, history_years=10, benchmark_bars=bench_bars,
    )
    assert [b["key"] for b in report["benchmarks"]] == [
        "sp500_buy_hold",
        "stock_buy_hold",
        "strategy_on_sp500",
    ]
    by_key = {b["key"]: b for b in report["benchmarks"]}
    assert by_key["sp500_buy_hold"]["available"] is True
    assert by_key["stock_buy_hold"]["available"] is True
    assert by_key["stock_buy_hold"]["metrics"]["train_validation"] is not None
    assert by_key["stock_buy_hold"]["metrics"]["test"] is not None
    if by_key["strategy_on_sp500"]["available"]:
        assert by_key["strategy_on_sp500"]["metrics"]["train_validation"] is not None

    assert report["assumptions"]["capital_gains_tax_short_term_pct"] == DEFAULT_SHORT_TERM_TAX_PCT
    assert report["assumptions"]["capital_gains_tax_long_term_pct"] == DEFAULT_LONG_TERM_TAX_PCT
    test_bars = report["split"]["test"]["bars"]
    for strategy in report["strategies"]:
        tv = strategy["metrics"]["train_validation"]
        assert "after_tax_total_return_pct" in tv
        assert "after_tax_cagr_pct" in tv
        equity = strategy.get("test_equity")
        assert equity is not None
        assert len(equity["dates"]) == test_bars
        assert len(equity["values"]) == len(equity["dates"])
        assert equity["values"][0] == pytest.approx(0.0, abs=1e-9)
        assert equity["values"][-1] == pytest.approx(strategy["metrics"]["test"]["total_return_pct"])

    stock_equity = by_key["stock_buy_hold"]["test_equity"]
    assert stock_equity is not None
    assert len(stock_equity["dates"]) == test_bars

    reduced = run_auto_tune(bars, window_days=90, history_years=10)
    availability = {b["key"]: b["available"] for b in reduced["benchmarks"]}
    assert availability == {
        "sp500_buy_hold": False,
        "stock_buy_hold": True,
        "strategy_on_sp500": False,
    }


def test_strategy_on_sp500_test_segment_uses_dedicated_test_backtest():
    n = 1100
    bars = _flat_bars(n)
    base = prepare_base_series(bars)
    ranges = _split_ranges(n)
    # 训练+验证段一笔交易（750 入场 / 800 离场）、测试段一笔交易（950 / 1000）
    signals = _manual_signals(n, buys=(749, 949), sells=(799, 999))

    class _StubEvaluator:
        def signals(self, thresholds):
            return signals

    bench_bars = _make_bars(
        [round(close * 1.5, 4) for close in _synthetic_closes(n)]
    )
    benchmarks = _build_benchmarks(
        base=base,
        ranges=ranges,
        evaluator=_StubEvaluator(),
        recommended_thresholds={},
        recommended_gen={"trend_filter": False, "volume_filter": False},
        rec_stop=None,
        rec_trail=None,
        window_days=90,
        cost_pct_per_side=0.1,
        short_term_tax_pct=35.0,
        long_term_tax_pct=15.0,
        benchmark_bars=bench_bars,
    )
    by_key = {b["key"]: b for b in benchmarks}
    sp_replay = by_key["strategy_on_sp500"]
    assert sp_replay["available"] is True
    tv_metrics = sp_replay["metrics"]["train_validation"]
    test_metrics = sp_replay["metrics"]["test"]
    assert tv_metrics is not None and tv_metrics["trades"] == 1
    # 回归：测试段必须来自推荐参数在个股测试段的独立回测，
    # 而不是从训练+验证段模拟里筛选（旧实现导致测试段永远为空）。
    assert test_metrics is not None and test_metrics["trades"] == 1

    test_start, test_end = ranges["test"]
    for key in ("sp500_buy_hold", "stock_buy_hold", "strategy_on_sp500"):
        equity = by_key[key]["test_equity"]
        assert equity is not None
        assert len(equity["dates"]) == test_end - test_start + 1
        assert len(equity["values"]) == len(equity["dates"])
        initial_return = (1.0 / 1.001 - 1.0) * 100.0 if key.endswith("buy_hold") else 0.0
        assert equity["values"][0] == pytest.approx(initial_return, abs=1e-4)
        assert equity["values"][-1] == pytest.approx(by_key[key]["metrics"]["test"]["total_return_pct"])


def test_trigger_benefits_include_extra_groups():
    bars = _make_bars(_synthetic_closes(400))
    computed = compute_indicators(bars)
    benefits = calculate_trigger_benefits(computed, window_days=20)

    expected_groups = ("macd", "kdj", "rsi", "obv", "boll", "cci", "dmi", "mfi")
    for group in expected_groups:
        entry = benefits[group]
        assert entry["label"] == group.upper()
        assert len(entry["benefit_series"]) == len(bars)
        assert "accumulated_benefit_pct" in entry
        assert "transactions" in entry
    # 新触发组以与经典组相同的买卖标记形式参与收益模拟
    for group in ("boll", "cci", "dmi", "mfi"):
        assert f"{group}_buy" in computed["triggers"]
        assert f"{group}_sell" in computed["triggers"]
