"""Real execution and historical-causality checks for the macro router."""

from copy import deepcopy
from datetime import date
import math

import pytest

from src.core import trading_calendar
from src.services.allocation.economic_reward import BenchmarkSeries, EconomicConfig
from src.services.indicator_optimizer import SAMPLED_CANDIDATES
from src.services.macro_execution import MacroExecutionEngine, MacroExecutionUnavailable, quarter_key


def _bars(start="2020-01-01", end="2020-06-30"):
    calendar = trading_calendar.xcals.get_calendar(trading_calendar.MARKET_EXCHANGE["us"])
    bars = []
    for index, session in enumerate(calendar.sessions_in_range(start, end)):
        close = 100 + index * .03 + 6 * math.sin(index / 7)
        bars.append(dict(date=session.date().isoformat(), open=close - .2, high=close + 1,
                         low=close - 1, close=close, volume=1_000_000))
    return bars


def _benchmark(bars):
    return BenchmarkSeries({bar["date"]: 300 + index * .1 for index, bar in enumerate(bars)}, adjusted=True)


def _engine(bars, **kwargs):
    kwargs.setdefault("benchmark", _benchmark(bars))
    return MacroExecutionEngine(bars, warmup_bars=0, candidate_count=2, **kwargs)


def _manual_signals(monkeypatch, buys, sells=(), allocation=1.):
    def signals(base, thresholds):
        return dict(
            buy_signal=[close if index in buys else None for index, close in enumerate(base["close"])],
            sell_signal=[close if index in sells else None for index, close in enumerate(base["close"])],
            buy_allocation=[allocation] * base["n"],
        )
    monkeypatch.setattr("src.services.macro_execution.compute_composite_signals", signals)


def test_quarter_key_is_shared_canonical_format():
    assert quarter_key("2024-01-02") == "2024Q1"
    assert quarter_key("2024-12-31") == "2024Q4"


def test_one_round_trip_next_open_and_no_reentry_with_actual_simulator(monkeypatch):
    bars = _bars()[:10]
    _manual_signals(monkeypatch, buys={0, 7}, sells={5}, allocation=.5)
    engine = _engine(bars, cost_pct_per_side=.1)
    result = engine._simulate("A", 0, engine.windows[0])
    assert len(result["trades"]) == 1
    trade = result["trades"][0]
    assert trade["entry_date"] == bars[1]["date"]
    assert trade["exit_date"] == bars[6]["date"]
    assert trade["exit_reason"] == "signal"
    assert trade["allocation_pct"] == 50
    assert trade["entry_price"] == pytest.approx(bars[1]["open"] * 1.001, abs=1e-4)
    assert trade["exit_price"] == pytest.approx(bars[6]["open"] * .999, abs=1e-4)
    assert any(item["reason"] in {"entry_cooldown", "trade_cooldown"} for item in result["decisions"])


def test_window_boundaries_discard_previous_signal_and_force_flat(monkeypatch):
    bars = _bars()[:20]
    _manual_signals(monkeypatch, buys={0, 9})
    engine = _engine(bars, cost_pct_per_side=0)
    first = engine._simulate("A", 0, engine.windows[0])
    second = engine._simulate("A", 0, engine.windows[1])
    assert first["trades"][0]["exit_date"] == bars[9]["date"]
    assert first["trades"][0]["exit_reason"] == "segment_end"
    assert len(first["trades"]) == 1
    assert second["trades"] == []
    assert second["equity"] == [1.] * 10


def test_exposure_counts_exclude_open_exit_and_include_window_close(monkeypatch):
    bars = _bars()[:20]
    _manual_signals(monkeypatch, buys={0, 10}, sells={5})
    engine = _engine(bars)
    families = engine.quarterly_outcomes()[0]["families"]
    windows = families["A"]["windows"]
    # First position is held sessions 1..5 and sold at session 6 open.
    # Second is held sessions 11..19, including the forced final close.
    assert [window["holding_bars"] for window in windows] == [5, 9]
    assert families["A"]["holding_bars"] == 14
    assert families["CASH"]["holding_bars"] == 0
    assert families["SPY_BuyHold"]["holding_bars"] == 20


def test_unfinished_window_not_closed_and_quarter_tail_is_closed():
    bars = _bars(end="2020-03-31")
    prefix = _engine(bars[:13])
    assert len(prefix.windows) == 1
    assert prefix.windows[-1]["end_date"] == bars[9]["date"]
    assert prefix.current_window_start == bars[10]["date"]
    assert prefix.quarterly_outcomes()[0]["complete"] is False
    ended = _engine(bars, as_of=date(2020, 4, 1))
    assert ended.windows[-1]["trading_bars"] == len(bars) % 10
    assert ended.windows[-1]["short_quarter_tail"] is True
    assert ended.windows[-1]["end_date"] == "2020-03-31"
    assert ended.quarterly_outcomes()[0]["complete"] is True


@pytest.mark.parametrize("missing_from", ["stock", "benchmark"])
def test_missing_session_does_not_compress_window_or_create_complete_quarter(missing_from):
    bars = _bars()
    benchmark = _benchmark(bars)
    baseline = _engine(bars, as_of=date(2020, 7, 1))
    absent = next(bar["date"] for bar in bars if bar["date"] >= "2020-05-06")
    if missing_from == "stock":
        bars = [bar for bar in bars if bar["date"] != absent]
    else:
        benchmark = BenchmarkSeries({day: price for day, price in benchmark.values.items() if day != absent},
                                    adjusted=True)
    engine = _engine(bars, benchmark=benchmark, as_of=date(2020, 7, 1))
    expected = [window for window in baseline.windows
                if not window["start_date"] <= absent <= window["end_date"]]
    assert [(window["start_date"], window["end_date"]) for window in engine.windows] == [
        (window["start_date"], window["end_date"]) for window in expected]
    result = {row["quarter"]: row for row in engine.quarterly_outcomes()}
    assert result["2020Q2"]["complete"] is False
    assert result["2020Q1"]["complete"] is True


def test_truncated_benchmark_and_partial_initial_quarter_not_usable_labels():
    bars = _bars()
    benchmark = _benchmark(bars[:-9])
    engine = _engine(bars[5:], benchmark=benchmark, as_of=date(2020, 7, 1))
    outcomes = engine.quarterly_outcomes()
    assert outcomes
    assert all(row["complete"] is False for row in outcomes)
    assert all(window["trading_bars"] <= 10 for window in engine.windows)


def test_parameters_and_outcomes_do_not_change_when_future_prices_change():
    bars = _bars(start="2019-07-01", end="2020-06-30")
    cutoff = "2020-05-15"
    prefix = [bar for bar in bars if bar["date"] <= cutoff]
    altered = deepcopy(bars)
    for bar in altered:
        if bar["date"] > cutoff:
            for key in ("open", "high", "low", "close"):
                bar[key] *= 4
    historical = _engine(prefix)
    future = _engine(altered, as_of=date(2020, 7, 1))
    before = {row["quarter"]: row for row in historical.quarterly_outcomes()}
    after = {row["quarter"]: row for row in future.quarterly_outcomes()}
    for quarter, row in before.items():
        for family in ("A", "B", "C", "D", "E", "F"):
            windows = row["families"][family]["windows"]
            assert windows == after[quarter]["families"][family]["windows"][:len(windows)]
            for window in windows:
                assert window["trained_through"] is None or window["trained_through"] < window["start_date"]
                assert len(window["trades"]) <= 1
    assert historical.parameters_for("F", cutoff) == future.parameters_for("F", cutoff)


def test_cash_is_zero_utility_and_target_cagr_and_benchmark_are_shared():
    bars = _bars(end="2020-03-31")
    engine = _engine(bars, economic_config=EconomicConfig(target_cagr=.12), as_of=date(2020, 4, 1))
    row = engine.quarterly_outcomes()[0]
    cash = row["families"]["CASH"]
    spy = row["families"]["SPY_BuyHold"]
    assert cash["utility"] == 0
    assert cash["return_pct"] == 0
    assert cash["target_cagr"] == .12
    elapsed = (date.fromisoformat(row["end_date"]) - date.fromisoformat(row["start_date"])).days
    assert cash["required_nav"] == pytest.approx(1.12 ** (elapsed / 365.25))
    assert spy["return_pct"] == pytest.approx(spy["benchmark_return_pct"])
    assert spy["relative_alpha_pct"] == pytest.approx(0.)
    assert len(row["dates"]) == len(cash["equity"]) == len(spy["equity"])


def test_calendar_is_required_even_when_benchmark_has_dates(monkeypatch):
    bars = _bars()[:10]
    monkeypatch.setattr(trading_calendar, "_XCALS_AVAILABLE", False)
    with pytest.raises(MacroExecutionUnavailable, match="calendar is unavailable"):
        _engine(bars)


def test_no_benchmark_cannot_produce_training_labels():
    engine = _engine(_bars(), benchmark=None, as_of=date(2020, 7, 1))
    assert all(not row["complete"] for row in engine.quarterly_outcomes())


def test_future_bars_excluded_at_constructor_cutoff():
    bars = _bars()
    engine = _engine(bars, as_of=date(2020, 2, 10))
    assert engine.dates[-1] == "2020-02-10"
    assert all(window["end_date"] <= "2020-02-10" for window in engine.windows)


def test_completed_tenth_session_selects_next_window_parameters():
    bars = _bars()[:10]
    engine = _engine(bars)
    upcoming = _bars()[10]["date"]
    assert engine.current_window_start == upcoming
    selection = engine.parameters_for("B")
    assert selection["training_windows"] == 1
    assert selection["trained_through"] == bars[-1]["date"]
    assert selection["selection_method"] == "default_insufficient_history"
    assert selection["candidate_index"] == 0
    assert selection["validation_windows"] == 0


def test_candidate_budget_matches_auto_tune_without_changing_baseline():
    bars = _bars()[:10]
    engine = MacroExecutionEngine(bars, warmup_bars=0)
    assert len(engine.candidates["A"]) == 1
    assert all(len(engine.candidates[family]) == SAMPLED_CANDIDATES + 1 for family in "BCDEF")


def test_short_lookback_keeps_explicit_defaults():
    bars = _bars(start="2019-07-01", end="2020-06-30")
    engine = _engine(bars, lookback_windows=12)
    selection = engine.parameters_for("E", "2020-07-01")
    assert selection["training_windows"] == 12
    assert selection["candidate_index"] == 0
    assert selection["selection_method"] == "default_insufficient_history"
    assert selection["fit_windows"] == selection["validation_windows"] == 0


def test_validation_rejects_candidate_that_only_won_earlier_training(monkeypatch):
    bars = _bars(start="2019-07-01", end="2020-06-30")
    template = _engine(bars)
    starts = {window["start_index"] for window in template.windows[:18]}
    # Candidate 1 buys the start of every window: profitable in the older
    # twelve windows, unprofitable in the six newer validation windows.
    # The default candidate produces no entries and should survive validation.
    for number, window in enumerate(template.windows):
        for index in range(window["start_index"], window["end_index"] + 1):
            offset = index - window["start_index"]
            price = 100 + (1 if number < 12 else -1) * offset * 2
            bars[index].update(open=price, high=price + .5, low=price - .5, close=price)

    def signals(base, thresholds):
        active = thresholds["composite_buy_threshold"] == 4
        return dict(buy_signal=[close if active and index in starts else None
                                for index, close in enumerate(base["close"])],
                    sell_signal=[None] * base["n"], buy_allocation=[1.] * base["n"])

    monkeypatch.setattr("src.services.macro_execution.compute_composite_signals", signals)
    engine = _engine(bars)
    engine.candidates["E"][1] = deepcopy(engine.candidates["E"][0])
    engine.candidates["E"][1]["thresholds"]["composite_buy_threshold"] = 4
    cutoff = engine.windows[18]["start_date"]
    chosen = engine.parameters_for("E", cutoff)
    assert chosen["selection_method"] == "chronological_train_validation"
    assert chosen["fit_windows"] == 12
    assert chosen["validation_windows"] == 6
    assert chosen["fit_through"] < chosen["validation_start"]
    assert chosen["validation_through"] < cutoff
    assert chosen["candidate_index"] == 0
    fit = engine.windows[:12]
    validation = engine.windows[12:18]
    assert engine._combine(fit, [engine._simulate("E", 1, window) for window in fit])["utility"] > 0
    assert engine._combine(validation, [engine._simulate("E", 1, window)
                                      for window in validation])["utility"] < 0


def test_missing_window_has_cash_equity_at_every_exchange_session():
    bars = _bars(end="2020-03-31")
    benchmark = _benchmark(bars)
    absent = bars[24]["date"]
    engine = _engine([bar for bar in bars if bar["date"] != absent], benchmark=benchmark,
                     as_of=date(2020, 4, 1))
    outcome = engine.quarterly_outcomes()[0]
    assert outcome["dates"] == [bar["date"] for bar in bars]
    for family in ("A", "B", "C", "D", "E", "F"):
        equity = outcome["families"][family]["equity"]
        assert len(equity) == len(bars)
        assert equity[20:30] == [equity[19]] * 10
