"""Deterministic ACES contracts through the real portfolio/research paths."""

from dataclasses import fields, replace
from datetime import date, timedelta
import math

import pytest

from src.services.aces.config import ACESConfig
from src.services.aces.optimizer import ACESStudy, preset_backtest
from src.services.aces.runtime import ACESRuntime, ACESState, ACESStateEncoder, prepare_context, validate_bars
from src.services.allocation.economic_reward import BenchmarkSeries
from src.services.allocation.fixed_score_policy import FixedScorePolicy
from src.services.allocation.portfolio_environment import PortfolioEnvironment
from src.services.allocation.simulator import simulate_allocation
from src.services.allocation.threshold_research import threshold_signals
from src.services.allocation.trigger_event import TriggerEvent


def fixture(n=650):
    prices = [100 + (i % 20) * .4 if i % 20 < 15 else 106 - (i % 20 - 14) for i in range(n)]
    dates = [(date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(n)]
    base = dict(n=n, dates=dates, close=prices, open=list(prices), high=[v + .1 for v in prices],
                low=[v - .1 for v in prices], atr=[1 + (i % 9) * .01 for i in range(n)],
                sma200=[90.] * n, volume=[1000.] * n, vol_sma20=[1000.] * n)
    scores = dict(buy_score=[{1: 3, 4: 5, 8: 8}.get(i % 20, 0) for i in range(n)],
                  sell_score=[8 if i % 20 == 15 else 0 for i in range(n)], buy_allocation=[.6] * n)
    benchmark = BenchmarkSeries({d: 100 * 1.0001 ** i for i, d in enumerate(dates)}, adjusted=True)
    return base, scores, benchmark


def test_preset_backtest_keeps_losing_trades_and_missing_benchmark_results():
    base, scores, _ = fixture()
    scores["buy_score"] = [0] * 650
    scores["sell_score"] = [0] * 650
    scores["buy_score"][500] = 8
    scores["sell_score"][530] = 8
    for i in range(500, 650):
        price = 100 - (i - 500) * .2
        for key in ("open", "close"):
            base[key][i] = price
        base["low"][i], base["high"][i] = price - .1, price + .1
    c = config(risk={"volatility_control": False})
    report = preset_backtest(base, scores, (500, 649), c, None, reason="Insufficient research history")
    row = report["policies"][0]
    assert report["simulation_status"] == "COMPLETED"
    assert report["research_status"] == "UNAVAILABLE"
    assert report["readiness"]["status"] == "WARN"
    assert row["metrics"]["test"]["total_return_pct"] < 0
    assert row["metrics"]["test"]["final_nav"] < 1
    assert [e["side"] for e in row["executions"]] == ["BUY", "SELL"]
    assert all(p["benchmark_nav"] is None for p in row["economic_curve"])
    assert c.allocation.economic.benchmark_missing_policy == "BLOCK"  # Request not mutated.


def config(**kwargs):
    values = dict(buy_thresholds=[4, 5], sell_thresholds=[-4, -5], purge_bars=20, q_finalists=1,
                  allocation={"validation_folds": 2, "q": {"episodes": 2}, "economic": {"allowed_max_drawdown": .4}},
                  execution={"buy_spacing_bars": 1, "min_trade_gap_bars": 1, "stop_multiple_atr": None,
                             "trail_multiple_atr": None, "cash_yield": .03},
                  risk={"maximum_exposure": .8, "maximum_turnover": 100, "maximum_fallback_fraction": 1.})
    values.update(kwargs)
    return ACESConfig.from_dict(values)


@pytest.mark.parametrize("values", [
    {"version": 999}, {"version": True}, {"allocation": {"state": {"use_regime": False}}},
    {"buy_thresholds": [0]}, {"sell_thresholds": [5]},
    {"risk": {"maximum_exposure": 1.1}}, {"risk": {"volatility_percentiles": [.8, .5, .9]}},
    {"allocation": {"q": {"minimum_visit_count": 0}}}, {"execution": {"cash_yield": -1}},
    {"execution": {"cost_pct_per_side": .01, "slippage_pct": .02}}, {"unknown": True},
])
def test_configuration_rejects_invalid_contract(values):
    with pytest.raises(ValueError):
        ACESConfig.from_dict(values)


def test_cash_yield_compounds_only_cash_and_preserves_inventory():
    env = PortfolioEnvironment(0)
    env.rebalance(.6, 100)
    env.accrue_cash(.05, 365.25)
    assert env.cash == pytest.approx(.42)
    assert env.shares == pytest.approx(.006)
    assert env.snapshot.nav == pytest.approx(1.02)


def test_seven_causal_state_dimensions_and_boundaries():
    assert len(fields(ACESState)) == 7
    assert not any("future" in f.name or "benchmark" in f.name for f in fields(ACESState))
    base, _, _ = fixture()
    c = config()
    base = prepare_context(base, c)
    encoder = ACESStateEncoder(c, base)
    env = PortfolioEnvironment(0)
    event = TriggerEvent(base["dates"][30], "BUY", 7, 100, 100, index=30, regime="BULL")
    env.rebalance(.4, 100)
    for dd, expected in [(0, "0_5"), (-.05, "5_10"), (-.1, "10_20"), (-.2, "20_30"), (-.3, "30_PLUS")]:
        state = encoder.encode(event, replace(env.snapshot, drawdown=dd))
        assert state.drawdown_bucket == expected
        assert state.trigger_bucket == "STRONG_BUY"
        assert state.cash_bucket == "50_70"
        assert state.regime == "BULL"


def test_past_only_volatility_and_risk_override():
    base, _, _ = fixture()
    c = config()
    original = prepare_context(base, c)
    changed = dict(base, atr=[v if i < 400 else 1000 for i, v in enumerate(base["atr"])])
    assert prepare_context(changed, c)["volatility_regime"][:400] == original["volatility_regime"][:400]
    original["volatility_regime"][30] = "EXTREME"
    runtime = ACESRuntime(c, original)
    env = PortfolioEnvironment(0)
    target, reason = runtime.risk.allow(1., env.snapshot, 30)
    assert target == .2 and reason == "VOLATILITY_CAP"
    target, reason = runtime.risk.allow(1., replace(env.snapshot, drawdown=-.5), 30)
    assert target == 0 and reason == "DRAWDOWN_LIMIT"


@pytest.mark.parametrize("delay, entry, exit_cost, end", [(0, 0, 0, 119), (1, .01, 0, 119), (0, 0, .01, 119), (0, 0, .01, 110)])
def test_synthetic_execution_risk_cash_and_counterfactual_reconcile(delay, entry, exit_cost, end):
    base, scores, benchmark = fixture()
    c = config()
    c = replace(c, execution=replace(c.execution, delay_bars=delay, entry_worsening=entry, exit_worsening=exit_cost))
    base = prepare_context(base, c)
    signals = threshold_signals(base, scores, 2, -4)
    result = simulate_allocation(base, signals, 30, end, FixedScorePolicy(),
                                 runtime=ACESRuntime(c, base), encoder=ACESStateEncoder(c, base),
                                 benchmark=benchmark, economic_config=c.allocation.economic,
                                 **ACESStudy.execution_args(c))
    assert result["equity"][0] == 1.
    assert sum(t["reward"] for t in result["transitions"]) == pytest.approx(math.log(result["equity"][-1]))
    assert len(result["score_observations"]) == end - 30 + 1
    assert result["economic_summary"]["required_nav"] > 1
    assert result["economic_summary"]["benchmark_return"] > 0
    assert any(t["risk_reason"] == "VOLATILITY_CAP" for t in result["transitions"])
    for t in result["transitions"]:
        if not t["execution"]:
            continue
        assert t["execution"]["after"]["cash"] >= -1e-12
        assert t["execution"]["after"]["shares"] >= 0
        if t["action_returns"]:
            # The actual replay must be one of the feasible counterfactual NAVs.
            assert min(abs(r["next_nav"] - t["nav_at_next_trigger"]) for r in t["action_returns"]) < 1e-9
    assert any(t["state_before"]["trigger_bucket"] == "WEAK_BUY" for t in result["transitions"])
    assert any(t["state_before"]["trigger_bucket"] == "STRONG_SELL" for t in result["transitions"])


def test_data_quality_rejects_preview_and_invalid_candles():
    bar = dict(date="2020-01-01", open=100, high=101, low=99, close=100)
    validate_bars([bar], last_confirmed_date=date(2020, 1, 1))
    with pytest.raises(ValueError, match="PREVIEW"):
        validate_bars([bar], last_confirmed_date=date(2019, 12, 31))
    with pytest.raises(ValueError, match="duplicate"):
        validate_bars([bar, bar], last_confirmed_date=date(2020, 1, 1))
    with pytest.raises(ValueError, match="OHLC"):
        validate_bars([dict(bar, low=102)], last_confirmed_date=date(2020, 1, 1))
    with pytest.raises(ValueError, match="volume"):
        validate_bars([dict(bar, volume=float("nan"))], last_confirmed_date=date(2020, 1, 1))
    base, scores, benchmark = fixture()
    for value in base.values():
        if isinstance(value, list):
            del value[200]
    for value in scores.values():
        del value[200]
    with pytest.raises(ValueError, match="missing stock sessions"):
        ACESStudy(base, scores, (0, 299), (320, 479), config(), benchmark)


def test_staged_search_purge_stress_and_frozen_test():
    base, scores, benchmark = fixture()
    c = config()
    study = ACESStudy(base, scores, (0, 299), (320, 479), c, benchmark)
    assert all(va[0] - tr[1] - 1 >= 20 for tr, va in study.folds)
    q_before = [dict(s.policies["Q_LEARNING"].table) for pair in study.q_pairs for s in study.studies[pair]]
    selected_before = study.selected
    # Changing test data after fitting cannot change selection or Q updates.
    for i in range(500, 650):
        base["close"][i] *= .8
        base["low"][i] *= .8
        base["open"][i] *= .8
    report = study.report((500, 649))
    assert study.selected == selected_before
    assert [dict(s.policies["Q_LEARNING"].table) for pair in study.q_pairs for s in study.studies[pair]] == q_before
    assert report["strategy_key"] == "G"
    assert report["simulation_status"] == "COMPLETED"
    assert report["test_risk_status"] in {"PASSED", "BREACH", "FAILED_CHECKS"}
    assert report["search_complexity"]["q_regions"] == 1
    assert len({id(s.policies["Q_LEARNING"].table) for pair in study.q_pairs for s in study.studies[pair]}) == 2
    assert not report["live_enabled"]
    assert all("buy_hold_nav" in p for r in report["policies"] for p in r["economic_curve"])
    with pytest.raises(ValueError, match="already"):
        study.report((500, 649))
    candidate = study.candidates[0]
    stress = study.stress(candidate)
    assert {r["scenario"] for r in stress} >= {"DOUBLE_COST", "DOUBLE_SLIPPAGE", "DELAY_ONE_DAY", "SKIP_SIGNALS", "NEIGHBOR_BUY_LOWER"}


def test_no_candidate_can_override_hard_sample_constraint():
    base, scores, benchmark = fixture()
    c = config(policy_mode="FIXED", risk={"minimum_trades": 1000})
    study = ACESStudy(base, scores, (0, 299), (320, 479), c, benchmark)
    assert study.selected is None
    assert all("MIN_TRADES" in row["failures"] for row in study.candidates)


def test_future_stock_and_benchmark_perturbation_before_fit_cannot_change_selection():
    base, scores, benchmark = fixture()
    c = config(policy_mode="FIXED")
    first = ACESStudy(base, scores, (0, 299), (320, 479), c, benchmark)
    changed = {k: list(v) if isinstance(v, list) else v for k, v in base.items()}
    for key in ("open", "high", "low", "close", "atr"):
        changed[key][500:] = [x * 10 for x in changed[key][500:]]
    changed_benchmark = BenchmarkSeries({d: p * (10 if i >= 500 else 1)
        for i, (d, p) in enumerate(benchmark.values.items())}, adjusted=True)
    second = ACESStudy(changed, scores, (0, 299), (320, 479), c, changed_benchmark)
    assert first.candidates == second.candidates
    assert first.selected == second.selected
    assert first.stress_results == second.stress_results


def test_cash_only_curve_and_dynamic_cost_are_explicit():
    base, scores, benchmark = fixture()
    c = config()
    c = replace(c, execution=replace(c.execution, volatility_slippage_factor=.01, liquidity_slippage_factor=.001))
    base = prepare_context(base, c)
    runtime = ACESRuntime(c, base)
    assert runtime.cost(30) > c.execution.cost_pct_per_side / 100
    scores = dict(scores, buy_score=[0] * 650, sell_score=[0] * 650)
    signals = threshold_signals(base, scores, 4, -4)
    result = simulate_allocation(base, signals, 30, 129, FixedScorePolicy(), runtime=runtime,
        encoder=ACESStateEncoder(c, base), benchmark=benchmark, economic_config=c.allocation.economic,
        **ACESStudy.execution_args(c))
    assert result["equity"][-1] == pytest.approx(1.03 ** (99 / 365.25))
    assert result["transaction_cost"] == 0
    assert result["economic_summary"]["cash_yield_assumption"] == "CONFIGURED_CONSTANT_PROXY"


def test_accepted_synthetic_candidate_can_pass_without_enabling_live_execution():
    base, scores, benchmark = fixture()
    # Deliberately broad synthetic stress tolerance verifies the positive path;
    # this setting is never used to retune the real historical holdout.
    study = ACESStudy(base, scores, (0, 299), (320, 479),
                      config(policy_mode="FIXED", stress_return_tolerance=.2), benchmark)
    assert study.selected is not None
    report = study.report((500, 649))
    assert report["readiness"]["status"] == "PASS"
    assert all(report["readiness"]["checks"].values())
    assert report["test_risk_status"] == "PASSED"
    assert report["live_enabled"] is False
