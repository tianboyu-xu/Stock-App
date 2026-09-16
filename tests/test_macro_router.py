"""MATR service uses the real execution and model paths with offline macro data."""

from datetime import date
from pathlib import Path
import math

import pytest

from data_provider.macro_data import MacroSnapshot, quarter_decision_date
from src.core import trading_calendar
from src.services.allocation.economic_reward import BenchmarkSeries
from src.services.macro_router import _decision, _scope, run_macro_router
from src.services.allocation.economic_reward import EconomicConfig


class OfflineMacroProvider:
    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)

    def get_snapshots(self, quarters):
        return {quarter: self.get_snapshot(quarter) for quarter in quarters}

    def get_snapshot(self, quarter):
        position = (int(quarter[:4]) - 2015) * 4 + int(quarter[-1])
        growth = math.sin(position * .7)
        return MacroSnapshot(
            quarter=quarter, decision_date=quarter_decision_date(quarter).isoformat(),
            features={"growth": growth, "inflation": math.cos(position * .5)},
            factor_scores={"growth": growth, "inflation": -.3},
            regime="Goldilocks" if growth >= 0 else "Slowdown", observations={},
            missing_features=(), snapshot_id=f"offline-fixture-{quarter}",
        )


@pytest.fixture(scope="module")
def market_history():
    calendar = trading_calendar.xcals.get_calendar("XNYS")
    dates = [day.date().isoformat() for day in calendar.sessions_in_range("2015-01-01", "2022-06-30")]
    bars = []
    benchmark = {}
    for i, day in enumerate(dates):
        price = 120 + .035 * i + 18 * math.sin(i * .06) + 5 * math.sin(i * .23)
        bars.append(dict(date=day, open=price * .999, high=price * 1.012,
                         low=price * .988, close=price, volume=1e6 + i * 100))
        benchmark[day] = 200 + i * .07 + 5 * math.sin(i * .03)
    return bars, BenchmarkSeries(benchmark, adjusted=True)


def test_full_service_quarter_forecast_and_real_two_week_execution(tmp_path, market_history):
    bars, benchmark = market_history
    report = run_macro_router(bars, symbol="AAPL", benchmark=benchmark,
                              price_basis="ADJUSTED_TOTAL_RETURN",
                              provider=OfflineMacroProvider(tmp_path), as_of=date(2022, 6, 30))
    assert report["status"] == "READY"
    current = report["current"]
    assert current["quarter"] == "2022Q2"
    assert current["feature_quarter"] == "2022Q1"
    assert current["training_through"] == "2022Q1"
    assert current["training_quarters"] >= 12
    assert current["as_of"] == "2022-03-31"
    assert {row["strategy_key"] for row in current["ranking"]} == set("ABCDEF") | {"CASH"}
    assert report["diagnostics"]["oos_quarters"] > 0
    for quarter in report["history"]:
        assert quarter["decision"]["training_through"] < quarter["quarter"]
        assert quarter["regret"] >= 0
        for window in quarter["windows"]:
            if window["trained_through"]:
                assert window["trained_through"] < window["start_date"]
            if window["entry_date"]:
                assert window["start_date"] < window["entry_date"] <= window["exit_date"] <= window["end_date"]
    # Public schema must retain the new report including causal/audit diagnostics.
    from tests.test_auto_tune_api_contract import _report_payload, response_model
    schema = response_model.__wrapped__()
    payload = _report_payload(False)
    payload["macro_router"] = report
    wire = schema(**payload).model_dump(mode="json")
    assert wire["macro_router"] == report
    complete_end = report["diagnostics"]["end_date"]
    complete_index = report["test_equity"]["dates"].index(complete_end)
    assert report["test_equity"]["values"][complete_index] == pytest.approx(report["diagnostics"]["total_return_pct"])
    assert report["benchmark_equity"]["dates"] == report["test_equity"]["dates"]
    assert report["benchmark_equity"]["values"][complete_index] == pytest.approx(report["diagnostics"]["spy_total_return_pct"])
    first = report["test_equity"]["dates"][0]
    assert report["diagnostics"]["spy_total_return_pct"] == pytest.approx(
        100 * (benchmark.values[complete_end] / benchmark.values[first] - 1))
    assert report["benchmark_equity"]["values"] == pytest.approx([
        100 * (benchmark.values[day] / benchmark.values[first] - 1)
        for day in report["test_equity"]["dates"]])
    # Completed windows from the open quarter are displayed, but are neither
    # macro labels nor completed-quarter diagnostic observations.
    open_quarter = report["history"][-1]
    assert open_quarter["quarter"] == current["quarter"]
    assert not open_quarter["complete"]
    assert report["test_equity"]["dates"][-1] == open_quarter["windows"][-1]["end_date"]
    assert report["test_equity"]["dates"][-1] > complete_end
    assert report["diagnostics"]["oos_quarters"] == sum(row["complete"] for row in report["history"])
    assert report["diagnostics"]["trade_count"] == sum(
        row["trade_count"] for row in report["history"] if row["complete"])
    assert 0 <= report["diagnostics"]["active_window_rate_pct"] <= 100
    assert 0 <= report["diagnostics"]["exposure_rate_pct"] <= 100
    for comparison in report["diagnostics"]["family_comparisons"]:
        family = comparison["strategy_key"]
        rows = [row for row in report["history"] if row["complete"]]
        assert comparison["total_return_pct"] == pytest.approx(
            100 * (math.prod(1 + row["family_returns"][family] / 100 for row in rows) - 1))
        assert comparison["trade_count"] == sum(row["family_statistics"][family]["trade_count"] for row in rows)
        assert 0 <= comparison["max_drawdown_pct"] <= 100


def test_published_quarter_survives_changed_and_shortened_history(tmp_path):
    snapshot = OfflineMacroProvider(tmp_path).get_snapshot("2022Q2")
    rows = []
    for i in range(20):
        quarter = f"{2016 + i // 4}Q{i % 4 + 1}"
        value = math.sin(i)
        rows.append(dict(quarter=quarter, features={"growth": value, "inflation": -value},
                         utilities={key: (.03 * value if key == "A" else -.03 * value)
                                    for key in "ABCDEF"}))
    scope = _scope("AAPL", EconomicConfig(), .1)
    first = _decision(rows, snapshot, tmp_path, scope, freeze=True)
    assert first["available"]
    assert _decision([], snapshot, tmp_path, scope, freeze=True) == first
    assert _decision([], snapshot, tmp_path, scope, freeze=False) == first
    assert len(list(tmp_path.rglob("2022Q2.json"))) == 1


def test_method_version_preserves_existing_frozen_scope(tmp_path, monkeypatch):
    from src.services import macro_router
    snapshot = OfflineMacroProvider(tmp_path).get_snapshot("2022Q2")
    rows = [dict(quarter=f"{2016 + i // 4}Q{i % 4 + 1}", features={"growth": math.sin(i)},
                 utilities={key: math.sin(i) * .03 for key in "ABCDEF"}) for i in range(20)]
    monkeypatch.setattr(macro_router, "ROUTER_VERSION", 1)
    old_scope = _scope("AAPL", EconomicConfig(), .1)
    _decision(rows, snapshot, tmp_path, old_scope, freeze=True)
    old_path = tmp_path / "decisions" / old_scope / "2022Q2.json"
    old_bytes = old_path.read_bytes()
    monkeypatch.setattr(macro_router, "ROUTER_VERSION", 2)
    new_scope = _scope("AAPL", EconomicConfig(), .1)
    assert old_scope != new_scope
    _decision(rows, snapshot, tmp_path, new_scope, freeze=True)
    assert old_path.read_bytes() == old_bytes
    assert len(list(tmp_path.rglob("2022Q2.json"))) == 2


def test_macro_failure_does_not_invent_current_economic_stage(tmp_path, market_history, monkeypatch):
    from data_provider.macro_data import MacroDataProvider
    def unexpected_search(self):
        pytest.fail("Unavailable macro data should be resolved before technical search")
    monkeypatch.setattr("src.services.macro_router.MacroExecutionEngine.quarterly_outcomes", unexpected_search)
    bars, benchmark = market_history
    report = run_macro_router(bars, symbol="AAPL", benchmark=benchmark,
                              price_basis="ADJUSTED_TOTAL_RETURN",
                              provider=MacroDataProvider(None, tmp_path), as_of=date(2022, 6, 30))
    assert report["status"] == "UNAVAILABLE"
    assert "FRED_API_KEY" in report["reason"]
    assert report["current"] is None
    assert not report["history"]


def test_unadjusted_or_non_us_inputs_have_explicit_status():
    assert run_macro_router([], symbol="600519")["status"] == "UNAVAILABLE"
    report = run_macro_router([], symbol="AAPL", price_basis="RAW")
    assert report["status"] == "UNAVAILABLE"
    assert "adjusted" in report["reason"]


def test_optional_invalid_price_data_returns_unavailable(tmp_path):
    report = run_macro_router([], symbol="AAPL", price_basis="ADJUSTED_TOTAL_RETURN",
                              benchmark=BenchmarkSeries({}, adjusted=True),
                              provider=OfflineMacroProvider(tmp_path), as_of=date(2022, 6, 30))
    assert report["status"] == "UNAVAILABLE"
    assert "daily bars" in report["reason"]


def test_missing_current_quarter_benchmark_retains_frozen_forecast(tmp_path, market_history):
    bars, benchmark = market_history
    options = dict(symbol="AAPL", price_basis="ADJUSTED_TOTAL_RETURN",
                   provider=OfflineMacroProvider(tmp_path), as_of=date(2022, 6, 30))
    original = run_macro_router(bars, benchmark=benchmark, **options)
    values = dict(benchmark.values)
    values.pop("2022-05-10")
    incomplete = run_macro_router(bars, benchmark=BenchmarkSeries(values, adjusted=True), **options)
    assert incomplete["status"] == "READY"
    assert incomplete["current"]["selected_strategy"] == original["current"]["selected_strategy"]
    assert incomplete["current"]["snapshot_id"] == original["current"]["snapshot_id"]
    assert any("Current-quarter performance unavailable" in warning for warning in incomplete["warnings"])
    assert all(row["quarter"] < "2022Q2" for row in incomplete["history"])
