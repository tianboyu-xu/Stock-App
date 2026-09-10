from copy import deepcopy
from datetime import date, timedelta

import pytest

from src.services.allocation.research import AllocationConfig, AllocationStudy, select_policy
from src.services.allocation.q_learning_policy import QLearningTrainer


def research_fixture():
    n = 90
    prices = [100 + (i % 10) for i in range(n)]
    base = dict(dates=[(date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(n)],
                close=prices, open=prices, low=prices, atr=[1.] * n,
                sma200=[None] * n, vol_sma20=[100.] * n, volume=[100.] * n)
    signals = dict(buy_signal=[p if i % 10 == 0 else None for i, p in enumerate(prices)],
                   sell_signal=[p if i % 10 == 8 else None for i, p in enumerate(prices)],
                   buy_score=[7] * n, sell_score=[5] * n, buy_allocation=[.7] * n)
    return base, signals


def fit(base=None, signals=None):
    if base is None:
        base, signals = research_fixture()
    return AllocationStudy(base, signals, (0, 29), (30, 59),
                           dict(cost_pct_per_side=.1, window_days=1, min_trade_gap_bars=1),
                           AllocationConfig.from_dict({"q": {"episodes": 20}}))


def test_fitting_and_final_test_are_separated_and_q_is_frozen():
    study = fit()
    before = study.policies["Q_LEARNING"].explain()
    report = study.report((60, 89))
    assert report["selected_policy"] == study.selected
    assert study.policies["Q_LEARNING"].explain() == before
    with pytest.raises(ValueError, match="already"):
        study.report((60, 89))


def test_perturbing_test_prices_does_not_change_fit_or_selection():
    base, signals = research_fixture()
    changed = deepcopy(base)
    for key in ("open", "close", "low"):
        changed[key][60:] = [p * 3 for p in changed[key][60:]]
    original, perturbed = fit(base, signals), fit(changed, signals)
    assert original.selected == perturbed.selected
    assert original.validation_scores == perturbed.validation_scores
    assert original.policies["Q_LEARNING"].explain() == perturbed.policies["Q_LEARNING"].explain()


def test_simpler_policy_wins_ties_and_poor_validation_rejects_q():
    assert select_policy({"TUNED_FIXED": .10, "Q_LEARNING": .105}, .01) == "TUNED_FIXED"
    assert select_policy({"CURRENT": .02, "TUNED_FIXED": .10, "Q_LEARNING": -.20}, .01) == "TUNED_FIXED"


def test_all_policies_report_separate_metrics_and_same_technical_triggers():
    report = fit().report((60, 89))
    assert [p["name"] for p in report["policies"]] == ["BUY_HOLD", "CURRENT", "FIXED", "TUNED_FIXED", "Q_LEARNING"]
    required = {"initial_nav", "final_nav", "total_return_pct", "cagr_pct", "sharpe", "sortino",
                "max_drawdown_pct", "win_rate_pct", "profit_factor", "trade_count", "turnover",
                "average_exposure_pct", "transaction_cost", "allocation_decisions", "budget_constrained_decisions"}
    for policy in report["policies"]:
        assert set(policy["metrics"]) == {"train", "validation", "test"}
        assert all(required <= set(metrics) for metrics in policy["metrics"].values())
        assert policy["metrics"]["test"]["total_return_pct"] == pytest.approx(policy["test_equity"]["values"][-1], abs=.0001)
    assert all(p["trigger_signature"] == report["policies"][1]["trigger_signature"] for p in report["policies"][1:])


def test_validation_prices_never_change_training_q_or_tuned_mapping():
    base, signals = research_fixture()
    changed = deepcopy(base)
    for key in ("open", "close", "low"):
        changed[key][30:60] = list(reversed(changed[key][30:60]))
    original, perturbed = fit(base, signals), fit(changed, signals)
    assert original.policies["Q_LEARNING"].explain() == perturbed.policies["Q_LEARNING"].explain()
    assert original.policies["TUNED_FIXED"].targets == perturbed.policies["TUNED_FIXED"].targets


def test_actual_overfit_episode_does_not_promote_q_on_training_profit():
    base, signals = research_fixture()
    prices = [100, 100] + [100 + 100 * (i - 1) / 28 for i in range(2, 30)]
    prices += [200, 200] + [200 - 100 * (i - 1) / 28 for i in range(2, 30)]
    prices += [100.] * 30
    for key in ("open", "close", "low"):
        base[key] = prices[:]
    signals["buy_signal"] = [prices[i] if i in (0, 30, 60) else None for i in range(90)]
    signals["sell_signal"] = [None] * 90
    study = AllocationStudy(base, signals, (0, 29), (30, 59),
                            dict(cost_pct_per_side=.1, window_days=1, min_trade_gap_bars=1),
                            AllocationConfig.from_dict({"q": {"episodes": 500, "minimum_visit_count": 1}}))
    report = study.report((60, 89))
    q = next(p for p in report["policies"] if p["name"] == "Q_LEARNING")
    assert q["metrics"]["train"]["total_return_pct"] > 90
    assert q["metrics"]["validation"]["total_return_pct"] < -40
    assert study.selected is None  # All validation policies breach the hard drawdown limit.


@pytest.mark.parametrize("settings", [[], {"policy_mode": "DQN"}, {"q": {"episodes": 0}},
    {"q": {"gamma": 1.1}}, {"q": {"episodes": 1.5}}, {"q": {"epsilon_start": .1, "epsilon_end": .3}},
    {"q": {"minimum_visit_count": -1}}, {"state": {"pnl_edges": [0, 0, 1, 2]}}, {"unknown": True}])
def test_invalid_research_config_is_rejected(settings):
    with pytest.raises(ValueError):
        AllocationConfig.from_dict(settings)


def test_mislabeling_validation_as_train_cannot_enable_updates():
    study = fit()
    trainer = QLearningTrainer(study.policies["TUNED_FIXED"])
    with pytest.raises(ValueError, match="training range"):
        study.simulate(trainer, study.validation, "TRAIN", observer=trainer.observe)
    assert trainer.table == {}
