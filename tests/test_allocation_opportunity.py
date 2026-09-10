from dataclasses import fields
import math

import pytest

from src.services.allocation.allocation_policy import PolicyDecision
from src.services.allocation.allocation_state import AllocationState, StateEncoder
from src.services.allocation.counterfactual_evaluator import CounterfactualEvaluator, foregone_regret
from src.services.allocation.portfolio_environment import PortfolioEnvironment
from src.services.allocation.score_observation import ScoreObservation
from tests.test_allocation_simulator import run


def portfolio(exposure=0, cost=0):
    env = PortfolioEnvironment(cost)
    env.rebalance(exposure, 100)
    return env.snapshot


@pytest.mark.parametrize("exposure,next_price,actions,action,positive", [
    (1, 120, [None, 1], 1, False),
    (.5, 120, [None, .6, .8, 1], None, True),
    (1, 80, [None, 1], None, False),
    (1, 80, [None, 0, .2, .4], None, True),
])
def test_symmetric_feasible_opportunity(exposure, next_price, actions, action, positive):
    result = CounterfactualEvaluator().evaluate(portfolio(exposure), actions, action, next_price)
    assert (result.regret > 0) == positive
    if exposure == 1 and next_price == 120:
        assert result.regret == 0


def test_best_feasible_action_costs_and_impossible_actions():
    evaluator = CounterfactualEvaluator()
    result = evaluator.evaluate(portfolio(), [None, .2, .4], .2, 120, transaction_cost=.01)
    assert result.best_feasible_action == .4
    env = PortfolioEnvironment(.01)
    env.rebalance(.4, 100)
    expected = math.log(env.mark_to_market(120).nav)
    assert result.best_feasible_return == pytest.approx(expected)
    assert all(row["action"] != 1 for row in result.action_returns)
    with pytest.raises(ValueError, match="infeasible"):
        evaluator.evaluate(portfolio(), [None, 1.2], None, 120)
    with pytest.raises(ValueError, match="feasible"):
        evaluator.evaluate(portfolio(), [None, .4], 1., 120)


def test_failed_sell_shortfall_is_downside_diagnostic_not_cash_penalty():
    result = foregone_regret("SELL", .2, 1., -.15)
    assert result["foregone_downside_regret"] == pytest.approx(.12)
    assert result["foregone_upside_regret"] == 0
    assert foregone_regret("BUY", 1, 1, .2)["foregone_upside_regret"] == 0


@pytest.mark.parametrize("buy,sell,forward,expected", [
    (3, -1, .2, "none"), (5, -1, .12, "buy"), (0, -5, -.15, "sell"),
    (4, -1, .2, "none"), (5, -1, -.2, "none"), (0, -5, .2, "none"),
])
def test_near_threshold_band_is_symmetric_and_bounded(buy, sell, forward, expected):
    observation = ScoreObservation("2026-01-01", buy, sell, 6, -6, False, .4, .6).evaluate(forward, 2)
    assert (observation.missed_buy_regret > 0) == (expected == "buy")
    assert (observation.missed_sell_regret > 0) == (expected == "sell")


def test_triggered_bar_has_no_threshold_penalty():
    observation = ScoreObservation("2026-01-01", 5, -5, 6, -6, True, .4, .6).evaluate(.2, 2)
    assert observation.missed_buy_regret == observation.missed_sell_regret == 0


def test_only_causal_state_and_policy_inputs():
    assert {f.name for f in fields(AllocationState)} == {
        "trigger_bucket", "exposure_bucket", "cash_bucket", "pnl_bucket", "regime"}

    class InspectPolicy:
        def choose(self, state, trigger, portfolio):
            assert trigger.execution_price == trigger.signal_price
            assert not hasattr(state, "opportunity_regret")
            return PolicyDecision(None, "HOLD")
    run(InspectPolicy(), prices=[100, 110, 90, 120, 80, 150, 70, 170, 100])


@pytest.mark.parametrize("cash,bucket", [(0, "0_10"), (.1, "10_30"), (.3, "30_50"),
                                           (.5, "50_70"), (.7, "70_100"), (1, "70_100")])
def test_cash_bucket_boundaries(cash, bucket):
    from src.services.allocation.trigger_event import TriggerEvent
    snapshot = portfolio(1 - cash)
    state = StateEncoder().encode(TriggerEvent("2026-01-01", "BUY", 8, 100, 100), snapshot)
    assert state.cash_bucket == bucket


@pytest.mark.parametrize("stop,trail", [(None, None), (1, None), (None, 1), (1, 1)])
def test_counterfactual_actual_path_matches_live_costs_stops_and_terminal(stop, trail):
    result = run(prices=[100, 100, 110, 105, 99, 100, 95, 105, 110], cost=.1,
                 stop_multiple_atr=stop, trail_multiple_atr=trail)
    for transition in result["transitions"]:
        if transition["execution"] is None:
            continue
        actual_nav = transition["nav_at_next_trigger"]
        # Match the actual effective action, including HOLD when blocked.
        effective = (transition["requested_target_exposure"] if transition["execution_reason"] in
                     {"TARGET_EXPOSURE", "BUDGET_CONSTRAINED", "SAME_TARGET"} else None)
        actual_row = next(row for row in transition["action_returns"] if row["action"] == effective)
        assert actual_row["next_nav"] == pytest.approx(actual_nav)
        assert transition["reward_after_regret"] == pytest.approx(
            transition["portfolio_reward"] - .25 * transition["opportunity_regret"]
            + transition["benchmark_reward"] - transition["cagr_penalty"])
    assert sum(t["portfolio_reward"] for t in result["transitions"]) == pytest.approx(math.log(result["equity"][-1]))
