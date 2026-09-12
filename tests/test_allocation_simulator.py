import math

import pytest

from src.services.allocation.fixed_score_policy import FixedScorePolicy, CurrentAllocationPolicy
from src.services.allocation.simulator import simulate_allocation
from src.services.allocation.q_learning_policy import QConfig, QLearningTrainer
from src.services.strategy_backtester import simulate_trades


def fixture(prices=None):
    prices = prices or [100.] * 9
    n = len(prices)
    base = dict(dates=[f"2026-01-{i + 1:02d}" for i in range(n)], close=prices, open=prices,
                low=[p - .1 for p in prices], atr=[1.] * n, sma200=[None] * n,
                volume=[100.] * n, vol_sma20=[100.] * n)
    signals = dict(buy_signal=[100., None, 100., None, 100., None, None, None, None][:n],
                   sell_signal=[None, None, None, None, None, 100., 100., 100., None][:n],
                   buy_score=[2, 0, 5, 0, 8, 0, 0, 0, 0][:n], sell_score=[0, 0, 0, 0, 0, 2, 5, 8, 0][:n],
                   buy_allocation=[.6] * n)
    return base, signals


def run(policy=None, prices=None, **kwargs):
    base, signals = fixture(prices)
    return simulate_allocation(base, signals, 0, len(base["close"]) - 1, policy or FixedScorePolicy(),
                               cost_pct_per_side=kwargs.pop("cost", 0), window_days=1,
                               min_trade_gap_bars=kwargs.pop("gap", 0), **kwargs)


def test_fixed_repeated_buy_sell_only_trade_differences():
    sim = run()
    executed = [r["execution"] for r in sim["transitions"]]
    assert [e["trade_value"] for e in executed] == pytest.approx([.6, .2, .2, -.6, -.2, -.2])
    assert all(e["after"]["cash"] >= 0 and e["after"]["shares"] >= 0 for e in executed)
    assert sim["equity"][-1] == pytest.approx(1)


def test_rewards_telescope_and_terminal_fee_is_included_once():
    sim = run(prices=[100., 100., 110., 110., 99., 99., 102., 105., 110.], cost=.001)
    assert sum(t["reward"] for t in sim["transitions"]) == pytest.approx(math.log(sim["equity"][-1]))
    assert sum(e["transaction_cost"] for e in sim["executions"]) == pytest.approx(sim["transaction_cost"])


def test_cooldown_and_protective_exits():
    sim = run(gap=5)
    assert sim["transitions"][1]["execution_reason"] == "TRADE_COOLDOWN"
    protected = run(prices=[100., 100., 80., 80., 100., 100., 100., 100., 100.], gap=5,
                    stop_multiple_atr=1)
    assert any(e["reason"] == "stop" for e in protected["executions"])


def test_chart_marks_include_partial_fills_and_protective_exits():
    sim = run()
    first, second = sim["executions"][:2]
    assert first["score"] == 2
    assert first["execution_price"] == 100
    assert first["holding_pct"] == pytest.approx(60)
    assert second["holding_pct"] == pytest.approx(80)
    assert second["trade_nav_pct"] == pytest.approx(20)
    protected = run(prices=[100., 100., 80., 80., 100., 100., 100., 100., 100.], gap=5,
                    stop_multiple_atr=1)
    stop = next(e for e in protected["executions"] if e["reason"] == "stop")
    assert stop["execution_price"] == 80
    assert stop["holding_pct"] == 0
    assert stop["score"] is None  # A protective exit is not a scored SELL trigger.


def test_identical_technical_triggers_under_different_policies():
    current = run(CurrentAllocationPolicy([.6] * 9, 0))
    fixed = run()
    assert current["trigger_signature"] == fixed["trigger_signature"]
    assert current["trade_count"] < fixed["trade_count"]


def test_no_learning_observer_allowed_on_validation_or_test():
    for phase in ["VALIDATION", "TEST"]:
        with pytest.raises(ValueError, match="forbidden"):
            run(phase=phase, observer=lambda *args: None)


def test_q_learning_learns_full_exposure_and_frozen_runs_do_not_learn():
    base, signals = fixture([100., 100., 110., 120.])
    signals["buy_signal"] = [100., None, None, None]
    signals["buy_score"] = [8, 0, 0, 0]
    config = QConfig(episodes=500, epsilon_start=.5, minimum_visit_count=1)
    def episode(policy, observer):
        return simulate_allocation(base, signals, 0, 3, policy, cost_pct_per_side=0,
                                   phase="TRAIN", observer=observer, trace=False)
    policies = [QLearningTrainer(FixedScorePolicy(), config).train(episode) for _ in range(2)]
    assert policies[0].explain() == policies[1].explain()
    frozen = policies[0]
    before = frozen.explain()
    for phase in ["VALIDATION", "TEST"]:
        sim = simulate_allocation(base, signals, 0, 3, frozen, cost_pct_per_side=0, phase=phase)
        assert sim["transitions"][0]["requested_target_exposure"] == 1
        assert sim["equity"][-1] == pytest.approx(1.2)
    assert frozen.explain() == before


@pytest.mark.parametrize("with_stop", [False, True])
def test_current_comparison_matches_existing_reference_accounting(with_stop):
    base, signals = fixture([100., 100., 80., 80., 100., 100., 105., 105., 110.])
    options = dict(cost_pct_per_side=.1, window_days=1, min_trade_gap_bars=0,
                   stop_multiple_atr=1 if with_stop else None)
    reference = simulate_trades(base, signals, 0, 8, size_by_score=True, **options)
    current = simulate_allocation(base, signals, 0, 8, CurrentAllocationPolicy(signals["buy_allocation"], .001), **options)
    assert current["equity"] == pytest.approx(reference["equity"])
    assert [t["exit_reason"] for t in current["trades"]] == [t["exit_reason"] for t in reference["trades"]]
