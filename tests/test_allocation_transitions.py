import json
import math
import pytest

from src.services.allocation import PortfolioEnvironment
from src.services.allocation.allocation_state import StateEncoder
from src.services.allocation.trigger_event import TriggerEvent
from src.services.allocation.allocation_transition import AllocationTransition
from src.services.allocation.allocation_transition import log_nav_reward


def test_transition_contains_requested_actual_and_portfolio_snapshots():
    env = PortfolioEnvironment(.001)
    event = TriggerEvent("2026-01-01", "BUY", 7, 100, 100)
    state = StateEncoder().encode(event, env.mark_to_market(100))
    record = AllocationTransition(event.timestamp, event.direction, event.score, state, env.snapshot,
                                  1.0, "FIXED_MAPPING", execution=env.rebalance(1, 100))
    wire = json.loads(json.dumps(record.to_dict(), allow_nan=False))
    assert wire["portfolio_before"]["cash"] == 1
    assert wire["execution"]["after"]["cash"] == 0
    assert wire["execution"]["requested_target_exposure"] == 1
    assert wire["execution"]["actual_target_exposure"] == 1
    assert wire["execution"]["reason"] == "BUDGET_CONSTRAINED"


def test_log_reward_telescopes_and_includes_unrealized_gains():
    assert log_nav_reward(1, 1.1) == pytest.approx(math.log(1.1))
    assert log_nav_reward(1, 1.1) + log_nav_reward(1.1, .99) == pytest.approx(math.log(.99))
    env = PortfolioEnvironment(.001)
    event = TriggerEvent("2026-01-01", "BUY", 7, 100, 100)
    before = env.mark_to_market(100)
    state = StateEncoder().encode(event, before)
    record = AllocationTransition(event.timestamp, "BUY", 7, state, before, 1, "FIXED_MAPPING")
    env.rebalance(1, 100)
    record.finish("2026-02-07", env.mark_to_market(110))
    assert 0 < record.reward < math.log(1.1)
    assert record.duration_days == 37
    assert env.shares > 0
    env.rebalance(0, 110)
    record.finish("2026-02-07", env.snapshot, terminal=True)
    assert record.reward == pytest.approx(math.log(1.1 * .999 / 1.001))


@pytest.mark.parametrize("start,end,days", [("2026-01-01", "2026-01-05", 4),
    ("2026-01-05", "2026-02-11", 37), ("2026-01-01", "2026-01-01", 0)])
def test_irregular_trigger_duration(start, end, days):
    env = PortfolioEnvironment(0)
    event = TriggerEvent(start, "BUY", 7, 100, 100)
    before = env.mark_to_market(100)
    record = AllocationTransition(start, "BUY", 7, StateEncoder().encode(event, before), before, 1, "FIXED_MAPPING")
    record.finish(end, before)
    assert record.duration_days == days
