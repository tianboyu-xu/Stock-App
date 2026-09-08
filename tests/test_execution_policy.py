# -*- coding: utf-8 -*-
"""Phase 6 tests: shared ExecutionPolicy (backtest == live).

- Unit: normal open / small gap / exact-limit boundary / over-limit /
  expiry / missing ATR.
- Parity: identical OHLCV through ``simulate_trades(max_entry_gap_atr=...)``
  and per-signal ``evaluate_entry`` calls produce the same decisions
  with the same reason codes.
"""

from datetime import date, timedelta

import pytest

from src.services.execution_policy import (
    DECISION_EXECUTE,
    DECISION_SKIP,
    REASON_GAP_TOO_LARGE,
    REASON_NO_ATR_DATA,
    REASON_OK,
    REASON_SIGNAL_EXPIRED,
    evaluate_entry,
)
from src.services.strategy_backtester import prepare_base_series, simulate_trades


def test_normal_next_open_executes_without_gap_rule():
    verdict = evaluate_entry(signal_close=100.0, next_open=100.5)
    assert verdict["decision"] == DECISION_EXECUTE
    assert verdict["reason"] == REASON_OK
    assert verdict["expected_execution"] == 100.5
    assert verdict["maximum_entry"] is None


def test_small_acceptable_gap_executes():
    verdict = evaluate_entry(
        signal_close=100.0, next_open=100.5, atr=2.0, max_entry_gap_atr=0.75,
    )
    assert verdict["decision"] == DECISION_EXECUTE
    assert verdict["reason"] == REASON_OK
    assert verdict["maximum_entry"] == pytest.approx(101.5)


def test_gap_exactly_at_limit_executes():
    # 边界含等于：确定性执行，不抛硬币。
    verdict = evaluate_entry(
        signal_close=100.0, next_open=101.5, atr=2.0, max_entry_gap_atr=0.75,
    )
    assert verdict["decision"] == DECISION_EXECUTE
    assert verdict["reason"] == REASON_OK


def test_gap_above_limit_skips():
    verdict = evaluate_entry(
        signal_close=100.0, next_open=101.51, atr=2.0, max_entry_gap_atr=0.75,
    )
    assert verdict["decision"] == DECISION_SKIP
    assert verdict["reason"] == REASON_GAP_TOO_LARGE


def test_gap_down_always_executes():
    verdict = evaluate_entry(
        signal_close=100.0, next_open=90.0, atr=2.0, max_entry_gap_atr=0.75,
    )
    assert verdict["decision"] == DECISION_EXECUTE


def test_expired_signal_skips():
    verdict = evaluate_entry(
        signal_close=100.0, next_open=100.1, atr=2.0,
        max_entry_gap_atr=0.75, signal_expired=True,
    )
    assert verdict["decision"] == DECISION_SKIP
    assert verdict["reason"] == REASON_SIGNAL_EXPIRED


def test_missing_atr_fails_closed_when_rule_enabled():
    verdict = evaluate_entry(
        signal_close=100.0, next_open=100.1, atr=None, max_entry_gap_atr=0.75,
    )
    assert verdict["decision"] == DECISION_SKIP
    assert verdict["reason"] == REASON_NO_ATR_DATA


def _bars_with_gap():
    # Flat 10.0 series; signal bar 20 close=10; fill bar 21 gaps up (ATR ready).
    bars = []
    current = date(2020, 1, 1)
    for i in range(30):
        price = 10.0
        bars.append({
            "date": current.isoformat(),
            "open": 12.0 if i == 21 else price,
            "high": (12.0 if i == 21 else price) + 0.06,
            "low": (12.0 if i == 21 else price) - 0.06,
            "close": price,
            "volume": 1_000_000.0,
        })
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


def test_backtest_and_live_policy_agree_on_gap_skip():
    bars = _bars_with_gap()
    base = prepare_base_series(bars)
    # Flat series ATR = 0.12 -> max entry = 10 + 0.75*0.12 = 10.09 < 12 -> skip.
    simulation = simulate_trades(
        base, _manual_signals(len(bars), buys=(20,), sells=(25,)),
        0, len(bars) - 1, window_days=1, cost_pct_per_side=0.0,
        max_entry_gap_atr=0.75,
    )
    assert simulation["trades"] == []
    (skip,) = simulation["skipped_entries"]
    assert skip["reason"] == REASON_GAP_TOO_LARGE
    assert skip["signal_date"] == bars[20]["date"]
    assert skip["maximum_entry"] == pytest.approx(10.0 + 0.75 * 0.12)

    # Same inputs through the live policy function: same verdict.
    live = evaluate_entry(
        signal_close=10.0, next_open=12.0, atr=0.12, max_entry_gap_atr=0.75,
    )
    assert live["decision"] == DECISION_SKIP
    assert live["reason"] == skip["reason"]
    assert live["maximum_entry"] == pytest.approx(skip["maximum_entry"])

    # Rule disabled (default): historical behavior fills at the gapped open.
    filled = simulate_trades(
        base, _manual_signals(len(bars), buys=(20,), sells=(25,)),
        0, len(bars) - 1, window_days=1, cost_pct_per_side=0.0,
    )
    assert len(filled["trades"]) == 1
    assert filled["trades"][0]["entry_price"] == pytest.approx(12.0)
    assert filled["skipped_entries"] == []


def test_small_gap_fills_in_backtest():
    bars = _bars_with_gap()
    bars[21]["open"] = bars[21]["high"] = 10.05
    bars[21]["low"] = 10.05 - 0.06
    base = prepare_base_series(bars)
    simulation = simulate_trades(
        base, _manual_signals(len(bars), buys=(20,), sells=(25,)),
        0, len(bars) - 1, window_days=1, cost_pct_per_side=0.0,
        max_entry_gap_atr=0.75,
    )
    assert len(simulation["trades"]) == 1
    assert simulation["skipped_entries"] == []
