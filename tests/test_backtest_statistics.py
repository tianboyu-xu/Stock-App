"""Uncertainty diagnostics and economic objective regression tests."""

import math

import pytest

from src.services.backtest_statistics import summarize_test_confidence
from src.services.strategy_backtester import objective_score


def _simulation(drift=0.0, count=252):
    equity = []
    value = 1.0
    for i in range(count):
        value *= 1 + drift + 0.01 * math.sin(i / 3)
        equity.append(value)
    return {"initial_equity": 1.0, "equity": equity, "trades": [{}, {}, {}]}


def test_confidence_is_reproducible_finite_and_does_not_mutate_equity():
    simulation = _simulation()
    original = list(simulation["equity"])
    result = summarize_test_confidence(simulation, seed=12)
    assert result == summarize_test_confidence(simulation, seed=12)
    assert simulation["equity"] == original
    assert result["available"]
    assert result["sharpe_ci_lower"] < 0 < result["sharpe_ci_upper"]
    assert 0 < result["positive_sharpe_fraction"] < 1
    assert result["valid_resamples"] == result["resamples"]


def test_positive_return_path_has_positive_conditional_interval():
    result = summarize_test_confidence(_simulation(drift=0.02))
    assert result["sharpe_ci_lower"] > 0
    assert result["positive_sharpe_fraction"] == 1


@pytest.mark.parametrize("simulation,reason", [
    (_simulation(count=20), "insufficient_history"),
    ({**_simulation(), "trades": []}, "insufficient_trades"),
    ({**_simulation(), "equity": [1.0] * 252}, "zero_variance"),
    ({**_simulation(), "initial_equity": 0}, "invalid_equity"),
    ({**_simulation(), "equity": [1e-300, 1e300] * 30}, "invalid_equity"),
])
def test_confidence_does_not_invent_precision_for_unusable_samples(simulation, reason):
    result = summarize_test_confidence(simulation)
    assert not result["available"]
    assert result["reason"] == reason
    assert result["sharpe_ci_lower"] is None


def test_objective_has_no_unattainable_turnover_target_or_redundant_metric_rewards():
    metrics = {"trades": 8, "sharpe": 1.0, "cagr_pct": 10, "max_drawdown_pct": -10}
    low_turnover = {**metrics, "trades_per_year": 2, "win_rate_pct": 40, "sortino": 1}
    high_turnover = {**metrics, "trades_per_year": 4, "win_rate_pct": 80, "sortino": 4}
    assert objective_score(low_turnover, 3) == objective_score(high_turnover, 3)
    assert objective_score(metrics, 3) > objective_score({**metrics, "cagr_pct": 8}, 3)
    assert objective_score(metrics, 3) > objective_score({**metrics, "max_drawdown_pct": -20}, 3)
    assert objective_score({**metrics, "trades": 1}, 3) < -100000
