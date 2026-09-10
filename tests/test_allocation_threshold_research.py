from copy import deepcopy
from datetime import date, timedelta

import pytest

from src.services.allocation.research import AllocationConfig
from src.services.allocation.threshold_research import ThresholdStudy, threshold_signals


def fixture():
    n = 120
    prices = [100, 100, 100, 120, 120, 120, 120, 100] * 15
    base = dict(dates=[(date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(n)],
                open=prices[:], close=prices[:], low=prices[:], atr=[1.] * n,
                sma200=[None] * n, vol_sma20=[100.] * n, volume=[100.] * n)
    scores = dict(buy_score=[0, 5, 5, 0, 0, 0, 0, 0] * 15,
                  sell_score=[0, 0, 0, 0, 6, 0, 0, 0] * 15, buy_allocation=[.7] * n)
    return base, scores


def fit(base=None, scores=None, mode="CURRENT", episodes=3):
    if base is None:
        base, scores = fixture()
    return ThresholdStudy(base, scores, (0, 47), (48, 95),
                          dict(cost_pct_per_side=.1, window_days=1, min_trade_gap_bars=1),
                          AllocationConfig.from_dict(dict(policy_mode=mode, threshold_iterations=1,
                                                          q=dict(episodes=episodes))),
                          buy_threshold=6, sell_threshold=-6)


def test_lower_threshold_captures_rallies_on_train_and_walk_forward():
    study = fit()
    assert study.selected_pair[0] == 5
    original_train = study.baseline.training_runs["CURRENT"]["equity"][-1]
    assert study.study.training_runs["CURRENT"]["equity"][-1] > original_train
    assert study.cache[study.selected_pair][1]["CURRENT"]["positive_folds"] == 3
    report = study.report((96, 119))
    assert report["joint_thresholds"]["selected"]["buy"] == 5
    assert len(report["joint_thresholds"]["candidates"]) == 9
    assert report["policies"][1]["name"] == "CURRENT"
    assert report["policies"][2]["name"] == "THRESHOLD_CURRENT"
    assert len(report["policies"][2]["score_observations"]) == 24


def test_each_threshold_and_fold_gets_independent_frozen_q_and_test_never_selects():
    study = fit(mode="AUTO")
    tables = [s.policies["Q_LEARNING"].table for studies, _ in study.cache.values() for s in studies]
    assert len({id(table) for table in tables}) == len(tables) == 27
    before = study.study.policies["Q_LEARNING"].explain()
    selected = study.selected_pair, study.selected
    report = study.report((96, 119))
    assert study.study.policies["Q_LEARNING"].explain() == before
    assert (study.selected_pair, study.selected) == selected
    assert {p["name"] for p in report["policies"]} >= {"CURRENT", "THRESHOLD_CURRENT", "TUNED_FIXED", "Q_LEARNING"}
    with pytest.raises(ValueError, match="already"):
        study.report((96, 119))


def test_final_prices_and_scores_cannot_change_search_candidates_q_or_selection():
    base, scores = fixture()
    changed, changed_scores = deepcopy(base), deepcopy(scores)
    for i in range(96, 120):
        for key in ("open", "close", "low"):
            changed[key][i] *= 1 + 5 * (i - 96)
        changed_scores["buy_score"][i] = 999
    original, altered = fit(base, scores, "AUTO"), fit(changed, changed_scores, "AUTO")
    assert original.selected_pair == altered.selected_pair
    assert original.selected == altered.selected
    assert original.cache.keys() == altered.cache.keys()
    for pair in original.cache:
        assert original.cache[pair][1] == altered.cache[pair][1]
        for first, second in zip(original.cache[pair][0], altered.cache[pair][0]):
            assert first.policies["Q_LEARNING"].explain() == second.policies["Q_LEARNING"].explain()


def test_threshold_signs_crossings_and_nontrigger_scores_preserved():
    base, scores = fixture()
    result = threshold_signals(base, scores, 5, -6)
    assert result["buy_signal"][1] == 100
    assert result["buy_signal"][2] is None
    assert result["buy_score"] is scores["buy_score"]
    assert result["sell_signal"][4] == 120
    with pytest.raises(ValueError, match="positive"):
        threshold_signals(base, scores, 5, 6)


def test_lambda_zero_preserves_portfolio_reward_and_selection_uses_actual_gain():
    from tests.test_allocation_simulator import run as simulate_fixture
    unshaped = simulate_fixture(lambda_opportunity=0, prices=[100, 100, 120, 100, 140, 140, 100, 100, 120])
    assert unshaped["opportunity_regret"] > 0
    assert all(t["reward_after_regret"] == pytest.approx(t["portfolio_reward"] - t["cagr_penalty"])
               for t in unshaped["transitions"])
    study = fit()
    # High return with some regret must beat tiny return with zero regret.
    from src.services.allocation.threshold_research import validation_objective
    run = deepcopy(study.study.validation_runs["CURRENT"])
    low = deepcopy(run)
    run["equity"][-1], run["opportunity_regret"] = 1.25, .08
    low["equity"][-1], low["opportunity_regret"] = 1.03, .01
    assert validation_objective(run, study.study.validation, .25) > validation_objective(low, study.study.validation, .25)


def test_training_winner_rejected_when_validation_prefers_higher_threshold():
    base, scores = fixture()
    # Validation: score 5 enters before a loss; score 6 arrives after the dip.
    # Every eight-bar cycle has an exit before the stronger signal.
    val_prices = [100, 100, 100, 80, 80, 80, 100, 100]
    for i in range(48, 96):
        j = (i - 48) % 8
        for key in ("open", "close", "low"):
            base[key][i] = val_prices[j]
        scores["buy_score"][i] = [0, 5, 0, 0, 6, 0, 0, 0][j]
        scores["sell_score"][i] = [0, 0, 6, 0, 0, 0, 6, 0][j]
    study = fit(base, scores)
    assert study.selected_pair[0] == 6
    # Final test rewards score 4 exclusively; that threshold is not selected.
    for i in range(96, 120):
        scores["buy_score"][i] = 4 if i % 8 == 1 else 0
    frozen = fit(base, scores)
    assert frozen.selected_pair[0] == 6
    frozen.report((96, 119))
    assert frozen.selected_pair[0] == 6
    from src.services.allocation.simulator import simulate_allocation
    hypothetical = simulate_allocation(base, threshold_signals(base, scores, 4, -6), 96, 119,
                                       frozen.study.policies["CURRENT"], cost_pct_per_side=.1,
                                       window_days=1, min_trade_gap_bars=1)
    actual = frozen.study.simulate(frozen.study.policies["CURRENT"], (96, 119), "TEST")
    assert hypothetical["equity"][-1] > actual["equity"][-1]
