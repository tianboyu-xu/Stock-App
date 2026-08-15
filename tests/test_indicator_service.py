# -*- coding: utf-8 -*-
"""Deterministic tests for the Excel "300 Plot" indicator logic."""

from src.services.indicator_service import (
    DEFAULT_THRESHOLDS,
    compute_indicators,
)


def _make_bars(closes, volume=1_000_000.0):
    bars = []
    for i, close in enumerate(closes):
        bars.append(
            {
                "date": f"2025-01-{i + 1:02d}",
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": float(close),
                "volume": float(volume),
            }
        )
    return bars


def test_sma_matches_window_average() -> None:
    closes = list(range(1, 31))  # 1..30
    result = compute_indicators(_make_bars(closes))
    sma5 = result["sma"]["5"]
    # First 4 values are None (insufficient window)
    assert sma5[:4] == [None, None, None, None]
    # SMA5 at index 4 = mean(1..5) = 3.0
    assert sma5[4] == 3.0
    # SMA5 at last index = mean(26..30) = 28.0
    assert sma5[-1] == 28.0


def test_sma200_requires_full_window() -> None:
    closes = [10.0] * 250
    result = compute_indicators(_make_bars(closes))
    sma200 = result["sma"]["200"]
    assert sma200[198] is None
    assert sma200[199] == 10.0
    assert sma200[-1] == 10.0


def test_ema_seeded_with_first_close() -> None:
    closes = [10.0] * 50
    result = compute_indicators(_make_bars(closes))
    ema12 = result["ema"]["12"]
    # Constant series -> EMA equals the constant
    assert all(abs(v - 10.0) < 1e-9 for v in ema12)


def test_macd_is_ema12_minus_ema26() -> None:
    closes = [float(i) for i in range(1, 61)]
    result = compute_indicators(_make_bars(closes))
    ema12 = result["ema"]["12"]
    ema26 = result["ema"]["26"]
    macd = result["macd"]
    for i in range(len(closes)):
        assert abs(macd[i] - (ema12[i] - ema26[i])) < 1e-9


def test_kdj_bounds_and_series_lengths() -> None:
    closes = [20 + (i % 7) for i in range(60)]
    result = compute_indicators(_make_bars(closes))
    n = len(closes)
    for key in ("k", "d", "j"):
        assert len(result[key]) == n
    # K and D stay within 0..100 once seeded
    for v in result["k"]:
        if v is not None:
            assert -1e-6 <= v <= 100.0 + 1e-6


def test_rsi_bounded_0_100() -> None:
    closes = [20 + (i % 5) * 0.8 for i in range(60)]
    result = compute_indicators(_make_bars(closes))
    for v in result["rsi"]:
        if v is not None:
            assert 0.0 <= v <= 100.0


def test_bollinger_band_ordering() -> None:
    closes = [20 + (i % 6) for i in range(60)]
    result = compute_indicators(_make_bars(closes))
    for upper, lower in zip(result["bolu"], result["bold"]):
        if upper is not None and lower is not None:
            assert upper > lower


def test_output_series_lengths_match_input() -> None:
    closes = [float(20 + i % 4) for i in range(80)]
    result = compute_indicators(_make_bars(closes))
    n = len(closes)
    assert len(result["dates"]) == n
    assert len(result["close"]) == n
    assert len(result["macd"]) == n
    assert len(result["obv"]) == n
    for series in result["triggers"].values():
        assert len(series) == n


def test_threshold_override_changes_triggers() -> None:
    closes = [20 + (i % 9) * 0.5 for i in range(120)]
    base = compute_indicators(_make_bars(closes))
    # Relax KDJ buy threshold to a very high value -> more buy triggers
    relaxed = compute_indicators(
        _make_bars(closes), {"kdj_buy": 95.0, "kdj_sell": 99.0}
    )
    base_buys = sum(1 for v in base["triggers"]["kdj_buy"] if v is not None)
    relaxed_buys = sum(1 for v in relaxed["triggers"]["kdj_buy"] if v is not None)
    assert relaxed_buys >= base_buys


def test_default_thresholds_match_excel() -> None:
    assert DEFAULT_THRESHOLDS == {
        "bol_constant": 0.1,
        "macd_buy": 0.7,
        "macd_sell": 0.99,
        "kdj_buy": 40.0,
        "kdj_sell": 70.0,
        "rsi_buy": 10.0,
        "rsi_sell": 70.0,
    }
