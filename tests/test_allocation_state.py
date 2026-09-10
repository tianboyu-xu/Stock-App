from src.services.allocation.trigger_event import TriggerEvent, events_from_signals
from src.services.allocation.allocation_state import StateConfig, StateEncoder
from src.services.allocation import PortfolioEnvironment
from dataclasses import replace
import pytest
from src.services.allocation.allocation_policy import get_valid_actions
from src.services.allocation.allocation_state import TARGET_EXPOSURES


def test_trigger_adapter_preserves_engine_events():
    base = dict(dates=["2026-01-01", "2026-01-02"], close=[100, 101], open=[99, 100], atr=[2, 2])
    signals = dict(buy_signal=[100, None], sell_signal=[None, 101], buy_score=[7, 0], sell_score=[0, 6])
    events = events_from_signals(base, signals, 0, 1)
    assert [(e.index, e.direction, e.signed_score) for e in events] == [(0, "BUY", 7), (1, "SELL", -6)]
    assert all(e.regime == "UNKNOWN" for e in events)
    assert events[0].execution_price == 100
    assert TriggerEvent("2026-01-01", "SELL", -7, 100, 100).signed_score == -7


@pytest.mark.parametrize("score,bucket", [(7, "STRONG_BUY"), (6, "MEDIUM_BUY"),
    (-7, "STRONG_SELL"), (-6, "MEDIUM_SELL"), (0, "NEUTRAL"), (3, "WEAK_BUY"), (-1, "WEAK_SELL")])
def test_score_boundaries(score, bucket):
    trigger = TriggerEvent("2026-01-01", "BUY" if score >= 0 else "SELL", score, 100, 100)
    assert StateEncoder().encode(trigger, PortfolioEnvironment(0).snapshot).trigger_bucket == bucket


@pytest.mark.parametrize("pnl,bucket", [(-.151, "LOSS_LARGE"), (-.15, "LOSS"),
    (-.05, "FLAT"), (.05, "FLAT"), (.15, "PROFIT"), (.151, "PROFIT_LARGE")])
def test_pnl_boundaries(pnl, bucket):
    snapshot = replace(PortfolioEnvironment(0).snapshot, unrealized_pnl_pct=pnl)
    assert StateEncoder().encode(TriggerEvent("d", "BUY", 7, 100, 100), snapshot).pnl_bucket == bucket


@pytest.mark.parametrize("exposure,expected", [(.39, .4), (.41, .4), (.3, .2), (0, 0), (1, 1)])
def test_exposure_boundaries(exposure, expected):
    snapshot = replace(PortfolioEnvironment(0).snapshot, current_exposure=exposure)
    state = StateEncoder().encode(TriggerEvent("d", "BUY", 7, 100, 100), snapshot)
    assert state.exposure_bucket == expected
    assert hash(state) == hash(state)


def test_config_and_regime():
    trigger = TriggerEvent("d", "BUY", 6, 100, 100, regime="BULL")
    state = StateEncoder(StateConfig(strong_score=6, use_regime=True)).encode(trigger, PortfolioEnvironment(0).snapshot)
    assert state.regime == "BULL" and state.trigger_bucket == "STRONG_BUY"
    with pytest.raises(ValueError):
        StateConfig(pnl_edges=(0, 0, 1, 2))


@pytest.mark.parametrize("exposure", TARGET_EXPOSURES)
@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_action_masks(exposure, direction):
    snapshot = replace(PortfolioEnvironment(0).snapshot, current_exposure=exposure)
    trigger = TriggerEvent("d", direction, 7, 100, 100)
    actions = get_valid_actions(snapshot, trigger)
    assert None in actions
    assert [a for a in actions if a is not None] == [
        a for a in TARGET_EXPOSURES if (a >= exposure if direction == "BUY" else a <= exposure)]


def test_off_grid_and_neutral_hold():
    snapshot = replace(PortfolioEnvironment(0).snapshot, current_exposure=.41)
    assert .4 not in get_valid_actions(snapshot, TriggerEvent("d", "BUY", 7, 100, 100))
    assert get_valid_actions(snapshot, TriggerEvent("d", "NEUTRAL", 0, 100, 100)) == (None,)
