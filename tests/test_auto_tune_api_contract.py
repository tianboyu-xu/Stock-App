"""Keep research diagnostics intact through the API's Pydantic response boundary."""

import importlib.util
import json
import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.services.backtest_statistics import summarize_test_confidence
from src.services.allocation.research import AllocationConfig, AllocationStudy
from src.services.strategy_backtester import (
    prepare_base_series,
    simulate_trades,
    summarize_metrics,
)


@pytest.fixture(scope="module")
def response_model():
    # api.v1 eagerly imports all routes. Load the real standalone schema so this
    # response-boundary test needs Pydantic, without unrelated database/LLM services.
    path = Path(__file__).resolve().parents[1] / "api" / "v1" / "schemas" / "stocks.py"
    spec = importlib.util.spec_from_file_location("auto_tune_stock_schemas", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AutoTuneResponse


def _report_payload(with_trades):
    """Use real accounting and confidence output in a representative report envelope."""
    start = date(2024, 1, 1)
    bars = []
    for i in range(90):
        price = 100.0 + 0.1 * i + math.sin(i / 4.0)
        bars.append({
            "date": (start + timedelta(days=i)).isoformat(),
            "open": price, "high": price + 1.0, "low": price - 1.0,
            "close": price, "volume": 1000.0,
        })
    buys, sells = [None] * len(bars), [None] * len(bars)
    if with_trades:
        for buy, sell in [(5, 15), (25, 40), (55, 75)]:
            buys[buy], sells[sell] = bars[buy]["close"], bars[sell]["close"]
    simulation = simulate_trades(
        prepare_base_series(bars), {"buy_signal": buys, "sell_signal": sells},
        0, len(bars) - 1, window_days=1,
    )
    metrics = summarize_metrics(simulation, 0, len(bars) - 1)
    confidence = summarize_test_confidence(simulation, seed=7)
    equity = {
        "dates": [bar["date"] for bar in bars],
        "values": [round((value - 1.0) * 100.0, 4) for value in simulation["equity"]],
    }
    fold = {
        "train": {"start_date": "2022-01-01", "end_date": "2022-12-31", "bars": 252},
        "validation": {"start_date": "2023-01-01", "end_date": "2023-12-31", "bars": 252},
    }
    thresholds = {"composite_buy_threshold": 5, "composite_sell_threshold": 5}
    allocation = AllocationStudy(
        prepare_base_series(bars), {"buy_signal": buys, "sell_signal": sells,
                                   "buy_score": [7] * len(bars), "sell_score": [7] * len(bars)},
        (0, 29), (30, 59), dict(cost_pct_per_side=.1, window_days=1, min_trade_gap_bars=1),
        AllocationConfig.from_dict({"q": {"episodes": 5}}),
    ).report((60, 89))
    return {
        "methodology_version": 6,
        "test_prices": {"dates": [bar["date"] for bar in bars], "values": [bar["close"] for bar in bars]},
        "allocation": allocation,
        "window_days": 90,
        "history": {"bars": 814, "start_date": "2021-01-01", "end_date": bars[-1]["date"]},
        "split": {
            **fold,
            "test": {"start_date": bars[0]["date"], "end_date": bars[-1]["date"], "bars": len(bars)},
        },
        "assumptions": {"execution": "next_open", "cost_pct_per_side": 0.1},
        "fixed_parameters": {},
        "walk_forward": {
            "folds": [fold], "aggregation": "median_objective_minus_population_stddev",
            "parameter_source": "latest_fold", "minimum_extra_validation_bars": 270,
        },
        "strategies": [{
            "key": "A", "name_en": "Baseline", "tuned": False,
            "params": {"thresholds": thresholds, "stop_multiple_atr": None, "trail_multiple_atr": None},
            "metrics": {"test": metrics}, "objectives": {"test": 0.2},
            "validation_score": 0.3, "validation_score_median": 0.4,
            "validation_score_dispersion": 0.1,
            "validation_folds": [{**fold, "metrics": metrics, "score": 0.4}],
            "test_equity": equity, "test_confidence": confidence,
            "test_decisions": simulation["decisions"],
        }],
        "recommended": {
            "strategy_key": "A", "reason_code": "baseline_sufficient", "eps": 0.05,
            "thresholds": thresholds,
        },
        "fine_tune": {
            "selection_basis": "validation", "aggregation": "median_objective_minus_population_stddev",
            "window_days": 120, "step": 24, "positions_tested": 1, "best_position_index": 0,
            "validation_folds": [fold["validation"]],
            "sweep": [{
                "position_index": 0, "best_strategy_key": "A", "validation_score": 0.3,
                "test_cagr": None, "thresholds": thresholds,
                "all_strategies": [{
                    "key": "A", "validation_cagr": 4.0, "validation_score": 0.3,
                    "test_cagr": None, "test_sharpe": None, "test_max_dd": None, "test_trades": None,
                }],
            }],
            "final_test": {
                "strategy_key": "A", "position_index": 0,
                "metrics": metrics, "equity": equity, "confidence": confidence,
            },
        },
    }


@pytest.mark.parametrize("with_trades", [False, True])
def test_auto_tune_api_roundtrip_preserves_research_diagnostics(with_trades, response_model):
    payload = _report_payload(with_trades)
    # FastAPI returns AutoTuneResponse(**report); by_alias matches response serialization.
    # The stock client then runs the existing deep toCamelCase converter on these keys.
    wire = json.loads(response_model.model_validate(payload).model_dump_json(by_alias=True))
    assert wire["methodology_version"] == 6
    assert wire["test_prices"] == payload["test_prices"]
    assert wire["allocation"] == json.loads(json.dumps(payload["allocation"]))
    assert wire["walk_forward"] == payload["walk_forward"]
    strategy = wire["strategies"][0]
    for key in (
        "validation_score", "validation_score_median", "validation_score_dispersion",
        "validation_folds", "test_confidence", "test_equity", "test_decisions",
    ):
        assert strategy[key] == payload["strategies"][0][key]
    assert strategy["test_confidence"]["available"] is with_trades
    assert strategy["test_confidence"]["reason"] == (None if with_trades else "insufficient_trades")
    assert strategy["test_equity"]["values"][-1] == strategy["metrics"]["test"]["total_return_pct"]
    assert wire["fine_tune"] == payload["fine_tune"]
    final_test = wire["fine_tune"]["final_test"]
    assert final_test["equity"]["values"][-1] == final_test["metrics"]["total_return_pct"]
    assert final_test["confidence"] == strategy["test_confidence"]


def test_legacy_auto_tune_payload_does_not_gain_current_methodology(response_model):
    payload = _report_payload(False)
    for key in ("methodology_version", "walk_forward", "fine_tune", "allocation"):
        payload.pop(key)
    for key in (
        "validation_score", "validation_score_median", "validation_score_dispersion",
        "validation_folds", "test_confidence",
    ):
        payload["strategies"][0].pop(key)
    wire = json.loads(response_model.model_validate(payload).model_dump_json(by_alias=True))
    # Deserialization must not relabel old cached results as safe to apply under version 2.
    assert wire["methodology_version"] is None
    assert wire["strategies"][0]["test_confidence"] is None
    assert wire["fine_tune"] is None


def test_aces_preset_results_and_null_research_metrics_survive_api(response_model):
    from tests.test_aces import fixture, config
    from src.services.aces.optimizer import preset_backtest
    base, scores, _ = fixture()
    payload = _report_payload(False)
    payload["aces"] = preset_backtest(base, scores, (500, 649), config(), None, reason="Missing benchmark")
    wire = json.loads(response_model.model_validate(payload).model_dump_json())
    assert wire["aces"] == json.loads(json.dumps(payload["aces"]))
    assert wire["aces"]["simulation_status"] == "COMPLETED"
    assert wire["aces"]["policies"][0]["metrics"]["validation"] is None
    assert wire["aces"]["policies"][0]["executions"]


def test_v2_joint_thresholds_and_daily_observations_survive_schema(response_model):
    from tests.test_allocation_threshold_research import fit
    payload = _report_payload(True)
    payload["allocation"] = fit(mode="AUTO").report((96, 119))
    wire = json.loads(response_model(**payload).model_dump_json())
    assert wire["allocation"]["joint_thresholds"] == payload["allocation"]["joint_thresholds"]
    row = next(p for p in wire["allocation"]["policies"] if p["name"] == "THRESHOLD_CURRENT")
    assert len(row["score_observations"]) == 24
    assert "cash_bucket" in row["transitions"][0]["state_before"]
    assert "reward_after_regret" in row["transitions"][0]
    assert "cagr_penalty" in row["transitions"][0]
    assert row["transitions"][0]["benchmark_return"] is None
    assert "economic_curve" in row
