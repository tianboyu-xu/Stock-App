"""Numerical regressions for the shared chart/backtest factor calculations."""

import pytest

from src.services.composite_factors import (
    compute_extra_factor_series,
    compute_extra_triggers,
)
from src.services.indicator_service import DEFAULT_THRESHOLDS


def _mixed_prices():
    close = [
        100, 103, 102, 106, 104, 107, 105, 105, 109, 104, 106, 103, 101, 104,
        102, 100, 99, 103, 101, 104, 100, 102, 106, 103, 107, 105, 108, 106,
        109, 104, 107, 103, 106, 102, 100, 103, 99, 102, 105, 101, 104, 108,
        105, 109, 106,
    ]
    high = [price + 1.0 + i % 3 * 0.25 for i, price in enumerate(close)]
    low = [price - 0.75 - i % 4 * 0.2 for i, price in enumerate(close)]
    return close, high, low, [1000.0] * len(close)


def test_dmi_adx_matches_independent_talib_reference():
    # Golden values generated from our fixture with TA-Lib 0.7.1, period 14,
    # unstable period 0. TA-Lib is not a runtime or test dependency.
    # Formula reference: https://github.com/TA-Lib/ta-lib/blob/main/src/ta_func/ta_ADX.c
    series = compute_extra_factor_series(*_mixed_prices())
    assert series["plus_di"][:14] == [None] * 14
    assert series["minus_di"][:14] == [None] * 14
    assert series["adx"][:27] == [None] * 27
    for i, plus, minus in [
        (14, 36.80373699483332, 31.22655531177013),
        (15, 34.34802270221382, 33.524889613787984),
        (27, 38.343219566065564, 31.089989558352087),
        (28, 41.333081977452366, 28.65198257294095),
        (40, 38.390486814173, 35.20648168821283),
        (44, 39.978290172109645, 34.085376042769255),
    ]:
        assert series["plus_di"][i] == pytest.approx(plus, rel=0, abs=1e-10)
        assert series["minus_di"][i] == pytest.approx(minus, rel=0, abs=1e-10)
    assert series["adx"][27:] == pytest.approx([
        9.397133022879697, 10.020175119869561, 9.513298054499609,
        9.475641462218379, 8.947200127137533, 8.728416346720893,
        8.425240104326711, 8.50085029175732, 7.9698765385266555,
        8.040083154275193, 7.515150439110569, 7.471982050696792,
        7.170715478282662, 6.967540952349052, 7.419227961154084,
        7.267223318756245, 7.746649192185464, 7.761642251221947,
    ], rel=0, abs=1e-10)


@pytest.mark.parametrize("direction", [-1, 1])
def test_unidirectional_trend_adx_is_100_without_inflation(direction):
    close = [1000.0 + direction * i for i in range(300)]
    series = compute_extra_factor_series(
        close, [price + 1.0 for price in close],
        [price - 1.0 for price in close], [1000.0] * len(close),
    )
    assert series["adx"][:27] == [None] * 27
    assert series["adx"][27:] == pytest.approx([100.0] * 273)
    for key in ("plus_di", "minus_di", "adx"):
        assert all(0.0 <= value <= 100.0 for value in series[key] if value is not None)


@pytest.mark.parametrize("length", [0, 1, 13, 14, 15, 27, 28, 100])
def test_flat_prices_keep_warmup_missing_then_return_zero(length):
    prices = [100.0] * length
    series = compute_extra_factor_series(prices, prices, prices, [0.0] * length)
    assert series["plus_di"] == [None] * min(14, length) + [0.0] * max(0, length - 14)
    assert series["minus_di"] == series["plus_di"]
    assert series["adx"] == [None] * min(27, length) + [0.0] * max(0, length - 27)


def test_low_adx_suppresses_crossovers_and_future_bars_cannot_change_past():
    prices = _mixed_prices()
    close = prices[0]
    series = compute_extra_factor_series(*prices)
    thresholds = {**DEFAULT_THRESHOLDS, "adx_min_level": 20.0}
    triggers = compute_extra_triggers(series, close, thresholds)
    assert all(value is None for value in triggers["dmi_buy"])
    assert all(value is None for value in triggers["dmi_sell"])
    relaxed = compute_extra_triggers(series, close, {**thresholds, "adx_min_level": 5.0})
    assert relaxed["dmi_sell"][31] == close[31]
    assert relaxed["dmi_buy"][32] == close[32]
    prefix = compute_extra_factor_series(*(values[:35] for values in prices))
    for key in ("plus_di", "minus_di", "adx"):
        assert prefix[key] == series[key][:35]
