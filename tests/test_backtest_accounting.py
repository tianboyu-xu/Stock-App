# -*- coding: utf-8 -*-
"""Phase 1 accounting acceptance tests with exact hand-computed numbers.

Covers the required deterministic cases:
- Test A: simple profitable trade (one entry cost + one exit cost only)
- Test B: losing trade (costs strictly increase the loss)
- Test G: exposure over known holding periods
- Test H: buy-and-hold benchmark matches manual calculation

Stop / trailing / gap / segment-end exits are covered in
``test_strategy_backtester.py::test_exit_paths_charge_each_side_once_and_reconcile_equity``
and ``test_gap_through_exit_level_fills_at_open_with_one_exit_fee``.
"""

from datetime import date, timedelta

import pytest

from src.services.strategy_backtester import (
    prepare_base_series,
    simulate_buy_hold,
    simulate_trades,
    summarize_metrics,
)


def _bars(prices, start=date(2020, 1, 1)):
    bars = []
    current = start
    for price in prices:
        bars.append(
            {
                "date": current.isoformat(),
                "open": float(price),
                "high": float(price) + 0.06,
                "low": float(price) - 0.06,
                "close": float(price),
                "volume": 1_000_000.0,
            }
        )
        current += timedelta(days=1)
    return bars


def _manual_signals(n, buys=(), sells=()):
    buy = [None] * n
    sell = [None] * n
    for i in buys:
        buy[i] = 1.0
    for i in sells:
        sell[i] = 1.0
    return {"buy_signal": buy, "sell_signal": sell}


def test_profitable_trade_charges_each_side_exactly_once():
    # Buy 100 (signal bar 0 -> fill bar 1 open), sell 110 (signal bar 2 -> fill bar 3).
    bars = _bars([100.0, 100.0, 110.0, 110.0, 110.0])
    simulation = simulate_trades(
        prepare_base_series(bars), _manual_signals(5, buys=(0,), sells=(2,)),
        0, 4, window_days=1, cost_pct_per_side=0.1,
    )
    (trade,) = simulation["trades"]
    entry = 100.0 * 1.001
    net_exit = 110.0 * 0.999
    expected_return = (net_exit / entry - 1.0) * 100.0
    assert trade["entry_price"] == pytest.approx(entry)
    assert trade["exit_price"] == pytest.approx(net_exit)
    assert trade["return_pct"] == pytest.approx(expected_return, abs=1e-4)
    assert trade["exit_reason"] == "signal"
    # Final equity must reconcile with the single trade (no double fee).
    assert simulation["equity"][-1] == pytest.approx(1.0 + expected_return / 100.0)
    metrics = summarize_metrics(simulation, 0, 4, 0.0, 0.0)
    assert metrics["total_return_pct"] == pytest.approx(expected_return, abs=1e-4)


def test_losing_trade_costs_increase_loss():
    bars = _bars([100.0, 100.0, 95.0, 95.0, 95.0])
    free = simulate_trades(
        prepare_base_series(bars), _manual_signals(5, buys=(0,), sells=(2,)),
        0, 4, window_days=1, cost_pct_per_side=0.0,
    )
    paid = simulate_trades(
        prepare_base_series(bars), _manual_signals(5, buys=(0,), sells=(2,)),
        0, 4, window_days=1, cost_pct_per_side=0.1,
    )
    free_return = (95.0 / 100.0 - 1.0) * 100.0
    paid_return = (95.0 * 0.999 / (100.0 * 1.001) - 1.0) * 100.0
    assert free["trades"][0]["return_pct"] == pytest.approx(free_return, abs=1e-4)
    assert paid["trades"][0]["return_pct"] == pytest.approx(paid_return, abs=1e-4)
    assert paid["trades"][0]["return_pct"] < free["trades"][0]["return_pct"] < 0


def test_exposure_matches_known_holding_periods():
    # Trade 1 holds bars 2..5 (4 bars), trade 2 holds bars 8..9 (2 bars).
    bars = _bars([10.0] * 12)
    simulation = simulate_trades(
        prepare_base_series(bars),
        _manual_signals(12, buys=(1, 7), sells=(5, 9)),
        0, 11, window_days=1, cost_pct_per_side=0.0,
    )
    assert len(simulation["trades"]) == 2
    assert simulation["holding_bars"] == 4 + 2
    metrics = summarize_metrics(simulation, 0, 11)
    assert metrics["exposure_pct"] == pytest.approx(6 / 12 * 100.0, abs=1e-9)


def test_buy_hold_matches_manual_calculation_with_costs():
    bars = _bars([100.0, 102.0, 105.0, 103.0, 110.0])
    simulation = simulate_buy_hold(
        prepare_base_series(bars), 0, 4, cost_pct_per_side=0.1,
    )
    (trade,) = simulation["trades"]
    entry = 100.0 * 1.001
    net_exit = 110.0 * 0.999
    expected = (net_exit / entry - 1.0) * 100.0
    assert trade["entry_price"] == pytest.approx(entry)
    assert trade["exit_price"] == pytest.approx(net_exit)
    assert trade["return_pct"] == pytest.approx(expected, abs=1e-4)
    assert trade["bars_held"] == 4
    assert simulation["equity"][-1] == pytest.approx(1.0 + expected / 100.0)
    # Intraday equity path keeps the entry cost from the first bar.
    assert simulation["equity"][0] == pytest.approx(100.0 / entry)
