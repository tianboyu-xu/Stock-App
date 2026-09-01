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


def test_default_thresholds_match_reference() -> None:
    assert DEFAULT_THRESHOLDS == {
        "bol_constant": 0.1,
        "macd_buy": 0.7,
        "macd_sell": 0.99,
        "kdj_buy": 40.0,
        "kdj_sell": 70.0,
        "rsi_buy": 10.0,
        "rsi_sell": 70.0,
        "composite_buy_threshold": 6.0,
        "composite_sell_threshold": 6.0,
        "macd_lookback": 120.0,
        "macd_low_percentile": 15.0,
        "macd_high_percentile": 85.0,
        "rsi_low": 15.0,
        "rsi_high": 85.0,
        "kdj_low": 40.0,
        "kdj_high": 70.0,
        "trend_period": 200.0,
        "momentum_period": 5.0,
        "momentum_min_change_pct": 0.25,
        "macd_fast": 12.0,
        "macd_slow": 26.0,
        "macd_signal": 9.0,
        "kdj_period": 9.0,
        "rsi_period": 14.0,
        "rsi_smooth_fast": 6.0,
        "rsi_smooth_slow": 14.0,
        "boll_buy_level": 0.1,
        "boll_sell_level": 0.9,
        "boll_weight": 0.0,
        "cci_buy_level": -100.0,
        "cci_sell_level": 100.0,
        "cci_weight": 0.0,
        "adx_min_level": 20.0,
        "dmi_weight": 0.0,
        "mfi_buy_level": 20.0,
        "mfi_sell_level": 80.0,
        "mfi_weight": 0.0,
        "volume_confirm_level": 1.5,
        "volume_weight": 0.0,
        "range52_high_level": 0.95,
        "range52_low_level": 1.05,
        "range52_weight": 0.0,
    }


def test_composite_series_lengths_match_input() -> None:
    closes = [float(20 + i % 4) for i in range(80)]
    result = compute_indicators(_make_bars(closes))
    n = len(closes)
    composite = result["composite"]
    assert len(composite["buy_score"]) == n
    assert len(composite["sell_score"]) == n
    assert len(composite["buy_signal"]) == n
    assert len(composite["sell_signal"]) == n
    assert len(composite["buy_breakdown"]) == n
    assert len(composite["sell_breakdown"]) == n


def test_composite_scores_bounded() -> None:
    from src.services.indicator_service import MAX_BUY_SCORE, MAX_SELL_SCORE

    closes = [float(20 + (i % 9) * 0.5) for i in range(250)]
    result = compute_indicators(_make_bars(closes))
    composite = result["composite"]
    assert composite["max_buy_score"] == 10
    assert composite["max_sell_score"] == 10
    assert MAX_BUY_SCORE == 10
    assert MAX_SELL_SCORE == 10
    for buy, sell in zip(composite["buy_score"], composite["sell_score"]):
        assert 0 <= buy <= 10
        assert 0 <= sell <= 10


def test_composite_breakdown_sums_match_score() -> None:
    closes = [float(20 + (i % 9) * 0.5) for i in range(250)]
    result = compute_indicators(_make_bars(closes))
    composite = result["composite"]
    expected_keys = {
        "macd", "kdj", "rsi", "regime", "momentum",
        "boll", "cci", "dmi", "mfi", "volume", "range52",
    }
    for i in range(len(closes)):
        buy_bd = composite["buy_breakdown"][i]
        sell_bd = composite["sell_breakdown"][i]
        assert set(buy_bd.keys()) == expected_keys
        assert set(sell_bd.keys()) == expected_keys
        assert sum(buy_bd.values()) == composite["buy_score"][i]
        assert sum(sell_bd.values()) == composite["sell_score"][i]


def test_composite_signal_requires_threshold() -> None:
    closes = [float(20 + (i % 9) * 0.5) for i in range(250)]
    result = compute_indicators(_make_bars(closes))
    composite = result["composite"]
    buy_threshold = int(DEFAULT_THRESHOLDS["composite_buy_threshold"])
    sell_threshold = int(DEFAULT_THRESHOLDS["composite_sell_threshold"])
    for i in range(len(closes)):
        if composite["buy_signal"][i] is not None:
            assert composite["buy_score"][i] >= buy_threshold
            # 信号仅在评分“进入”阈值区间的那根 bar 触发
            prev_buy = composite["buy_score"][i - 1] if i > 0 else 0
            assert prev_buy < buy_threshold
        if composite["sell_signal"][i] is not None:
            assert composite["sell_score"][i] >= sell_threshold
            prev_sell = composite["sell_score"][i - 1] if i > 0 else 0
            assert prev_sell < sell_threshold


def test_composite_signal_uses_current_bar_close() -> None:
    closes = [float(20 + (i % 9) * 0.5) for i in range(250)]
    result = compute_indicators(_make_bars(closes))
    composite = result["composite"]
    for i in range(len(closes)):
        if composite["buy_signal"][i] is not None:
            assert composite["buy_signal"][i] == closes[i]
        if composite["sell_signal"][i] is not None:
            assert composite["sell_signal"][i] == closes[i]


def test_composite_threshold_override_increases_signals() -> None:
    closes = [float(20 + (i % 9) * 0.5) for i in range(250)]
    base = compute_indicators(_make_bars(closes))
    relaxed = compute_indicators(
        _make_bars(closes),
        {"composite_buy_threshold": 1.0, "composite_sell_threshold": 1.0},
    )
    base_buys = sum(1 for v in base["composite"]["buy_signal"] if v is not None)
    relaxed_buys = sum(1 for v in relaxed["composite"]["buy_signal"] if v is not None)
    base_sells = sum(1 for v in base["composite"]["sell_signal"] if v is not None)
    relaxed_sells = sum(1 for v in relaxed["composite"]["sell_signal"] if v is not None)
    assert relaxed_buys >= base_buys
    assert relaxed_sells >= base_sells


def test_percentile_rank_rolling_window() -> None:
    from src.services.indicator_service import _percentile_rank

    # Current value is the window max -> 100th percentile.
    assert _percentile_rank([1.0, 2.0, 3.0], 3.0) == 100.0
    # Current value is the window min -> low percentile.
    assert _percentile_rank([1.0, 2.0, 3.0], 1.0) == 100.0 / 3.0
    # Empty window -> None（无数据时不给分，与参考实现一致）
    assert _percentile_rank([], 5.0) is None


def test_composite_macd_factor_requires_reversal() -> None:
    # 250 flat bars, then a 30-bar decline, then a 30-bar recovery.
    closes = (
        [100.0] * 250
        + [100.0 - i * 1.5 for i in range(1, 31)]
        + [55.0 + i * 1.5 for i in range(1, 31)]
    )
    result = compute_indicators(_make_bars(closes))
    composite = result["composite"]
    bottom_index = 250 + 30 - 1  # last decline bar (close = 55.0)
    # At the price bottom MACD is still falling -> no reversal factor yet.
    assert composite["buy_breakdown"][bottom_index]["macd"] == 0
    # Some bar after the bottom must award the MACD deep-reversal factor.
    assert any(
        bd["macd"] == 2
        for bd in composite["buy_breakdown"][bottom_index + 1:]
    )


def test_composite_macd_factor_requires_full_window() -> None:
    # 回看窗口未满时 MACD 百分位不计分（避免早期样本过少导致失真）
    closes = [float(20 + (i % 9) * 0.5) for i in range(250)]
    result = compute_indicators(_make_bars(closes))
    composite = result["composite"]
    lookback = int(DEFAULT_THRESHOLDS["macd_lookback"])
    for i in range(min(lookback, len(closes))):
        assert composite["buy_breakdown"][i]["macd"] == 0
        assert composite["sell_breakdown"][i]["macd"] == 0


def test_composite_momentum_requires_price_direction_confirmation() -> None:
    # 阶段一：持续下跌但跌幅逐日收窄 —— ROC 环比改善但当日仍在下跌，
    # 动量因子要求价格同向确认，因此不得给 BUY 动量分。
    # 阶段二：下跌后回升 —— ROC 改善且当日上涨，应给 BUY 动量分。
    closes = [100.0] * 30
    price = 100.0
    step = 1.5
    for _ in range(60):
        price -= step
        step = max(0.05, step - 0.05)
        closes.append(price)
    for _ in range(20):
        price += 0.3
        closes.append(price)

    composite = compute_indicators(_make_bars(closes))["composite"]
    period = int(DEFAULT_THRESHOLDS["momentum_period"])

    def roc(i: int) -> float:
        return (closes[i] - closes[i - period]) / closes[i - period] * 100.0

    # 样本中确实存在“ROC 改善但当日下跌”的 bar（证明抑制路径被覆盖）
    assert any(
        i >= period + 1
        and closes[i] < closes[i - 1]
        and roc(i) > roc(i - 1)
        for i in range(len(closes))
    )

    buy_momentum_bars = 0
    for i in range(len(closes)):
        buy_mom = composite["buy_breakdown"][i]["momentum"]
        sell_mom = composite["sell_breakdown"][i]["momentum"]
        # 动量因子买卖互斥，且必须与当日价格方向一致
        assert not (buy_mom == 2 and sell_mom == 2)
        if buy_mom == 2:
            assert closes[i] > closes[i - 1]
            buy_momentum_bars += 1
        if sell_mom == 2:
            assert closes[i] < closes[i - 1]
    assert buy_momentum_bars > 0


def test_composite_ambiguous_bar_suppresses_both_signals() -> None:
    closes = [float(20 + (i % 9) * 0.5) for i in range(250)]
    overrides = {"composite_buy_threshold": 1.0, "composite_sell_threshold": 1.0}
    composite = compute_indicators(_make_bars(closes), overrides)["composite"]
    buy_th = int(overrides["composite_buy_threshold"])
    sell_th = int(overrides["composite_sell_threshold"])
    for i in range(len(closes)):
        prev_buy = composite["buy_score"][i - 1] if i > 0 else 0
        prev_sell = composite["sell_score"][i - 1] if i > 0 else 0
        buy_enter = composite["buy_score"][i] >= buy_th and prev_buy < buy_th
        sell_enter = composite["sell_score"][i] >= sell_th and prev_sell < sell_th
        if buy_enter and sell_enter:
            # 同一根 bar 双向同时进入区间视为方向不明，不产生任何标记。
            # 该情形在常规行情中极难出现（买卖因子分别在底部/顶部触发），
            # 此处做不变量校验：一旦出现，两侧信号都必须为 None。
            assert composite["buy_signal"][i] is None
            assert composite["sell_signal"][i] is None
        else:
            if buy_enter:
                assert composite["buy_signal"][i] is not None
            if sell_enter:
                assert composite["sell_signal"][i] is not None


def test_backtester_composite_matches_indicator_service() -> None:
    from src.services.strategy_backtester import (
        compute_composite_signals,
        prepare_base_series,
    )

    closes = [float(20 + (i % 9) * 0.5) for i in range(250)]
    bars = _make_bars(closes)
    composite = compute_indicators(bars)["composite"]

    base = prepare_base_series(bars)
    signals = compute_composite_signals(base, None)

    assert signals["buy_score"] == composite["buy_score"]
    assert signals["sell_score"] == composite["sell_score"]
    assert signals["buy_signal"] == composite["buy_signal"]
    assert signals["sell_signal"] == composite["sell_signal"]


def _make_trending_bars(n=300):
    """温和上行 + 尾部放量的日线，用于触发量能/52 周位置等扩展因子。"""
    bars = []
    for i in range(n):
        close = 50.0 + 0.15 * i + 1.2 * ((i % 7) - 3)
        volume = 2_000_000.0 if i >= n - 60 else 800_000.0
        bars.append(
            {
                "date": f"2025-01-{i + 1:02d}",
                "open": close - 0.4,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": float(close),
                "volume": float(volume),
            }
        )
    return bars


def test_extra_factor_weights_raise_max_score_and_contribute() -> None:
    bars = _make_trending_bars()
    overrides = {
        "boll_weight": 2.0,
        "cci_weight": 2.0,
        "dmi_weight": 2.0,
        "mfi_weight": 2.0,
        "volume_weight": 2.0,
        "range52_weight": 2.0,
    }
    composite = compute_indicators(bars, overrides)["composite"]
    baseline = compute_indicators(bars)["composite"]
    # 满分 = 经典 10 分 + 启用权重和（2*6 = 12）
    assert composite["max_buy_score"] == 22
    assert composite["max_sell_score"] == 22
    assert baseline["max_buy_score"] == 10
    assert baseline["max_sell_score"] == 10
    for buy, sell in zip(composite["buy_score"], composite["sell_score"]):
        assert 0 <= buy <= 22
        assert 0 <= sell <= 22
    # 权重启用后分数不低于基线，且至少一根 bar 实际加分
    assert all(
        buy >= base for buy, base in zip(composite["buy_score"], baseline["buy_score"])
    )
    assert any(
        buy > base for buy, base in zip(composite["buy_score"], baseline["buy_score"])
    )
    extra_keys = {"boll", "cci", "dmi", "mfi", "volume", "range52"}
    contributed = sum(
        sum(bd[key] for key in extra_keys)
        for bd in composite["buy_breakdown"]
    ) + sum(
        sum(bd[key] for key in extra_keys)
        for bd in composite["sell_breakdown"]
    )
    assert contributed > 0


def test_extra_trigger_groups_markers_match_close() -> None:
    bars = _make_trending_bars()
    computed = compute_indicators(bars)
    n = len(bars)
    for group in ("boll", "cci", "dmi", "mfi"):
        for direction in ("buy", "sell"):
            series = computed["triggers"][f"{group}_{direction}"]
            assert len(series) == n
            for i, value in enumerate(series):
                if value is not None:
                    assert abs(value - float(bars[i]["close"])) < 1e-9


def test_extra_factor_parity_between_service_and_backtester() -> None:
    from src.services.strategy_backtester import (
        compute_composite_signals,
        prepare_base_series,
    )

    bars = _make_trending_bars()
    overrides = {
        "boll_buy_level": 0.15,
        "boll_sell_level": 0.85,
        "boll_weight": 2.0,
        "cci_buy_level": -120.0,
        "cci_sell_level": 120.0,
        "cci_weight": 1.0,
        "adx_min_level": 15.0,
        "dmi_weight": 2.0,
        "mfi_buy_level": 25.0,
        "mfi_sell_level": 75.0,
        "mfi_weight": 1.0,
        "volume_confirm_level": 1.2,
        "volume_weight": 2.0,
        "range52_high_level": 0.9,
        "range52_low_level": 1.1,
        "range52_weight": 1.0,
    }
    composite = compute_indicators(bars, overrides)["composite"]
    signals = compute_composite_signals(prepare_base_series(bars), overrides)

    assert signals["buy_score"] == composite["buy_score"]
    assert signals["sell_score"] == composite["sell_score"]
    assert signals["buy_signal"] == composite["buy_signal"]
    assert signals["sell_signal"] == composite["sell_signal"]
