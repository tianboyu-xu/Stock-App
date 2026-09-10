import math

import pytest

from src.services.allocation import PortfolioEnvironment


def test_initial_state():
    state = PortfolioEnvironment(0.001).snapshot
    assert (state.nav, state.cash, state.shares, state.current_exposure) == (1, 1, 0, 0)


def test_incremental_targets_and_full_exit_manual_accounting():
    env = PortfolioEnvironment(0)
    for target, expected_trade in [(0.4, .4), (.8, .4), (.2, -.6), (0, -.2)]:
        trade = env.rebalance(target, 100)
        assert trade.trade_value == pytest.approx(expected_trade)
        assert trade.after.stock_value == pytest.approx(target)
        assert trade.after.cash == pytest.approx(1 - target)
        assert trade.after.nav == pytest.approx(1)
    assert env.shares == 0


def test_fee_aware_target_and_cost_once():
    env = PortfolioEnvironment(.001)
    trade = env.rebalance(.6, 100)
    notional = .6 / 1.0006
    assert trade.trade_value == pytest.approx(notional)
    assert env.cash == pytest.approx(1 - notional * 1.001)
    assert trade.after.nav == pytest.approx(1 - notional * .001)
    assert trade.actual_target_exposure == pytest.approx(.6)
    assert env.rebalance(.6, 100).side == "HOLD"
    assert env.total_transaction_cost == pytest.approx(notional * .001)
    exit_trade = env.rebalance(0, 100)
    assert env.cash == pytest.approx(1 - 2 * notional * .001)
    assert exit_trade.realized_profit == pytest.approx(-2 * notional * .001)


def test_mark_to_market_cost_basis_and_unrealized_gain():
    env = PortfolioEnvironment(0)
    env.rebalance(.6, 100)
    state = env.mark_to_market(110)
    assert state.nav == pytest.approx(1.06)
    assert state.unrealized_pnl_pct == pytest.approx(.1)
    env.rebalance(.2, 110)
    assert env.average_cost == pytest.approx(100)


@pytest.mark.parametrize("target", [-.1, 1.1, math.nan, math.inf])
def test_rejects_leverage_and_invalid_targets(target):
    env = PortfolioEnvironment(.001)
    with pytest.raises(ValueError):
        env.rebalance(target, 100)
    assert env.snapshot.nav == 1


def test_budget_constraint_and_repeated_buys_sells_never_create_capital():
    env = PortfolioEnvironment(.001)
    first = env.rebalance(1, 100)
    assert first.reason == "BUDGET_CONSTRAINED"
    assert first.after.nav == pytest.approx(1 / 1.001)
    assert env.rebalance(1, 100).side == "HOLD"
    for target in [.8, .2, 0, 0, .4, 1, 1, 0]:
        result = env.rebalance(target, 100)
        assert result.after.cash >= 0 and result.after.shares >= 0
        assert 0 <= result.actual_target_exposure <= 1
        assert result.after.nav == pytest.approx(1 - env.total_transaction_cost)
