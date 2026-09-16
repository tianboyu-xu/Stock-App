"""Causal quarter selection, nested validation and abstention regressions."""

import copy
from dataclasses import replace
import math

import pytest
import numpy as np

from src.services.macro_router_model import (
    DEFAULT_SETTINGS, _selection_policy, correlation_evidence, select_strategy,
)


def history(count=32):
    rows = []
    for i in range(count):
        growth = math.sin(i * .7)
        rows.append({"quarter": f"{2010 + i // 4}Q{i % 4 + 1}",
                     "features": {"growth": growth, "inflation": math.cos(i * .31), "constant": 7.},
                     "utilities": {"A": .035 * growth + .004,
                                   "B": -.035 * growth - .001}})
    return rows


def test_router_learns_environment_and_uses_whole_quarter_inner_folds():
    rows = history()
    target = {"quarter": "2018Q1", "features": {"growth": 1., "inflation": -.5, "constant": 7.}}
    result = select_strategy(rows, target, ["A", "B"])
    assert result["selected_strategy"] == "A"
    assert "growth" in result["top_features"]
    assert "constant" not in result["top_features"]
    for candidate in result["inner_validation"]:
        assert len(candidate["folds"]) == 4
        for fold in candidate["folds"]:
            assert fold["trained_through"] < fold["quarter"] < target["quarter"]
    target["features"]["growth"] = -1.
    assert select_strategy(rows, target, ["A", "B"])["selected_strategy"] == "B"


def test_held_out_and_future_quarters_cannot_change_prediction_or_scaling():
    rows = history(40)
    target = {"quarter": rows[25]["quarter"], "features": rows[25]["features"]}
    expected = select_strategy(rows[:25], target, ["A", "B"])
    changed = copy.deepcopy(rows)
    for row in changed[25:]:
        row["utilities"] = {"A": 1e10, "B": -1e10}
        row["features"] = {"growth": 1e20, "inflation": -1e20, "constant": 999.}
    assert select_strategy(changed, target, ["A", "B"]) == expected


def test_correlation_measures_relative_advantage_not_shared_bull_market_return():
    rows = history()
    initial = correlation_evidence(rows, ["A", "B"])
    for i, row in enumerate(rows):
        for family in row["utilities"]:
            row["utilities"][family] += i * .4
    shifted = correlation_evidence(rows, ["A", "B"])
    assert shifted == initial


def test_cash_for_insufficient_history_negative_utilities_and_missing_features():
    rows = history()
    target = {"quarter": "2018Q1", "features": {"growth": .9, "inflation": .1}}
    assert select_strategy(rows[:8], target, ["A", "B"])["available"] is False
    missing = select_strategy(rows, {**target, "features": {}}, ["A", "B"])
    assert missing["selected_strategy"] == "CASH"
    assert missing["reason"] == "missing_selected_features"
    for row in rows:
        row["utilities"] = {key: value - .2 for key, value in row["utilities"].items()}
    result = select_strategy(rows, target, ["A", "B"])
    assert result["selected_strategy"] == "CASH"
    assert result["ranking"][0]["strategy_key"] == "CASH"


def test_duplicate_quarters_do_not_masquerade_as_more_independent_samples():
    rows = history()
    with pytest.raises(ValueError, match="one independent row"):
        select_strategy(rows + [rows[0]], {"quarter": "2018Q1"}, ["A", "B"])


def test_nonfinite_utility_is_rejected():
    rows = history()
    rows[0]["utilities"]["A"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        select_strategy(rows, {"quarter": "2018Q1"}, ["A", "B"])


def test_inner_validation_applies_same_cash_advantage_abstention_as_final_route():
    rows = history()
    target = {"quarter": "2018Q1", "features": {"growth": 1., "inflation": -.5, "constant": 7.}}
    ordinary = select_strategy(rows, target, ["A", "B"])
    cautious = select_strategy(
        rows, target, ["A", "B"], settings=replace(DEFAULT_SETTINGS, confidence_error_fraction=1000.),
    )
    assert any(fold["selected_strategy"] != "CASH"
               for candidate in ordinary["inner_validation"] for fold in candidate["folds"])
    assert cautious["selected_strategy"] == "CASH"
    for candidate in cautious["inner_validation"]:
        assert candidate["objective"] == 0
        assert len(candidate["calibration_quarters"]) == 4
        for fold in candidate["folds"]:
            assert fold["prediction_error"] > 0
            assert fold["confidence_threshold"] == pytest.approx(1000 * fold["prediction_error"])
            assert 0 < fold["score_gap"] < fold["confidence_threshold"]
            assert fold["selected_strategy"] == "CASH"


def test_profitable_near_substitutes_do_not_force_cash():
    def choose(scores, families):
        fit = dict(scores=np.array(scores), analog=np.array(scores), usable=True)
        return _selection_policy(fit, families, .10, DEFAULT_SETTINGS)

    single = choose([.03], ["A"])
    duplicate = choose([.03, .03], ["A", "B"])
    close = choose([.03, .0299], ["A", "B"])
    assert single[0] == duplicate[0] == close[0] == "A"
    assert duplicate[2] == 0  # Family uncertainty does not erase cash advantage.
    assert close[2] < DEFAULT_SETTINGS.confidence_error_fraction * .10
    assert all(result[3] for result in (single, duplicate, close))


@pytest.mark.parametrize("scores", [[-.03, -.04], [0., 0.], [.005, -.04], [.01, -.04]])
def test_cash_still_wins_when_advantage_is_negative_or_below_error_hurdle(scores):
    fit = dict(scores=np.array(scores), analog=np.array(scores), usable=True)
    chosen, _, _, eligible = _selection_policy(fit, ["A", "B"], .10, DEFAULT_SETTINGS)
    assert chosen == "CASH"
    assert not eligible


def test_positive_scores_require_usable_features_and_prior_error_calibration():
    fit = dict(scores=np.array([.03, .02]), analog=np.array([.03, .02]), usable=True)
    assert _selection_policy(fit, ["A", "B"], None, DEFAULT_SETTINGS)[0] == "CASH"
    fit["usable"] = False
    assert _selection_policy(fit, ["A", "B"], .01, DEFAULT_SETTINGS)[0] == "CASH"


def test_inner_fold_label_cannot_calibrate_its_own_confidence_or_selection():
    rows = history()
    target = {"quarter": "2018Q1", "features": {"growth": 1., "inflation": -.5, "constant": 7.}}
    expected = select_strategy(rows, target, ["A", "B"])
    changed = copy.deepcopy(rows)
    # Index 28 is the first scored inner fold; its realized label may affect
    # subsequent learning but not its own feature fit, confidence or choice.
    for row in changed[-4:]:
        row["utilities"] = {"A": 1e6, "B": -1e6}
    actual = select_strategy(changed, target, ["A", "B"])
    for original, modified in zip(expected["inner_validation"], actual["inner_validation"]):
        before, after = original["folds"][0], modified["folds"][0]
        assert before["quarter"] == rows[-4]["quarter"]
        for key in ("selected_strategy", "score_gap", "prediction_error", "confidence_threshold"):
            assert after[key] == before[key]
