from dataclasses import fields, replace
import math

import pytest

from src.services.allocation.economic_reward import (
    BenchmarkDataMissing, BenchmarkSeries, EconomicConfig, benchmark_component,
    cagr_snapshot, evaluate_economic_reward,
)
from src.services.allocation.allocation_state import AllocationState
from src.services.allocation.threshold_research import ThresholdStudy
from src.services.allocation.research import AllocationConfig
from tests.test_allocation_simulator import run
from tests.test_allocation_threshold_research import fixture


@pytest.mark.parametrize("nav,positive", [(1.3, False), (1.4, False), (1.2, True)])
def test_one_year_hurdle(nav, positive):
    point = cagr_snapshot(1., nav, 365.25, EconomicConfig())
    assert (point["current_cagr_deficit"] > 1e-12) == positive
    assert point["required_nav"] == pytest.approx(1.3)


def test_early_gain_stagnation_and_incremental_deficit_only():
    config = EconomicConfig()
    early = cagr_snapshot(1., 1.4, 30, config)
    assert early["current_cagr_deficit"] == 0
    assert cagr_snapshot(1., 1.4, 365, config)["current_cagr_deficit"] == 0
    assert cagr_snapshot(1., 1.4, 500, config)["current_cagr_deficit"] > 0
    result = evaluate_economic_reward("2021-01-01", "2022-01-01", 1.2, 1.2 * 1.3 ** (365 / 365.25),
                                      initial_date="2020-01-01", config=config)
    assert result["previous_cagr_deficit"] > 0
    assert result["cagr_deficit_increase"] == pytest.approx(0, abs=1e-12)
    assert result["cagr_penalty"] == pytest.approx(0, abs=1e-12)


def test_recovery_is_not_charged_and_short_cagr_is_immature():
    result = evaluate_economic_reward("2021-01-01", "2021-01-02", 1., 2., initial_date="2020-01-01")
    assert result["cagr_penalty"] == 0
    assert cagr_snapshot(1., 1.01, 3, EconomicConfig())["actual_cagr"] is None
    assert cagr_snapshot(1., 1.01, 90, EconomicConfig())["actual_cagr"] is not None


@pytest.mark.parametrize("strategy,bench,sign,reason", [
    (.10, .05, 1, "BEAT_BENCHMARK"), (.05, .10, 0, "PROFIT_BUT_TRAILED_BENCHMARK"),
    (-.10, -.03, -1, "UNDERPERFORMED_BENCHMARK"), (-.05, -.15, 1, "BEAT_BENCHMARK_IN_DECLINE"),
])
def test_benchmark_cases(strategy, bench, sign, reason):
    config = EconomicConfig()
    reward, actual_reason = benchmark_component(math.log1p(strategy), math.log1p(bench), config)
    assert (1 if reward > 0 else -1 if reward < 0 else 0) == sign
    assert actual_reason == reason
    assert -config.lambda_underperform * config.alpha_penalty_cap <= reward <= config.lambda_alpha * config.alpha_reward_cap


def test_margin_caps_and_zero_interval():
    config = replace(EconomicConfig(), alpha_margin=.001, alpha_reward_cap=.02, alpha_penalty_cap=.01)
    assert benchmark_component(.08001, .08, config)[0] == 0
    assert benchmark_component(.5, -.5, config)[0] == .02
    assert benchmark_component(-.5, .5, config)[0] == -.005
    assert benchmark_component(0, 0, config)[0] == 0


def test_missing_benchmark_is_unknown_and_strict_mode_blocks():
    result = evaluate_economic_reward("2020-01-01", "2020-02-01", 1., 1.01, initial_date="2020-01-01")
    assert result["benchmark_return"] is None
    assert result["benchmark_reward_reason"] == "BENCHMARK_DATA_MISSING"
    with pytest.raises(BenchmarkDataMissing):
        evaluate_economic_reward("2020-01-01", "2020-02-01", 1., 1.01, initial_date="2020-01-01",
                                 config=replace(EconomicConfig(), benchmark_missing_policy="BLOCK"))
    with pytest.raises(ValueError, match="adjusted"):
        BenchmarkSeries({"2020-01-01": 100}, adjusted=False)


def test_exact_interval_no_forward_fill_and_immutable_benchmark():
    series = BenchmarkSeries({"2020-01-01": 100, "2020-01-21": 105, "2020-01-31": 120}, adjusted=True)
    result = evaluate_economic_reward("2020-01-01", "2020-01-21", 1., 1.10,
                                      initial_date="2020-01-01", benchmark=series)
    assert result["benchmark_return"] == pytest.approx(.05)
    assert result["benchmark_start_timestamp"] == "2020-01-01"
    assert result["benchmark_end_timestamp"] == "2020-01-21"
    with pytest.raises(TypeError):
        series.values["2020-01-01"] = 200
    missing = evaluate_economic_reward("2020-01-02", "2020-01-21", 1., 1.1,
                                       initial_date="2020-01-01", benchmark=series)
    assert missing["benchmark_return"] is None


def test_combined_reward_has_no_second_fee_and_does_not_change_nav():
    benchmark = BenchmarkSeries({f"2026-01-{i + 1:02d}": 100 + i for i in range(9)}, adjusted=True)
    prices = [100, 100, 110, 105, 99, 100, 95, 105, 110]
    result = run(prices=prices, cost=.1, benchmark=benchmark)
    plain = run(prices=prices, cost=.1, economic_config=EconomicConfig(lambda_cagr=0, lambda_alpha=0, lambda_underperform=0))
    assert result["equity"] == plain["equity"]
    for t in result["transitions"]:
        assert t["reward_after_regret"] == pytest.approx(t["portfolio_reward"] + t["benchmark_reward"]
                                                        - .25 * t["opportunity_regret"] - t["cagr_penalty"])
    assert sum(t["portfolio_reward"] for t in result["transitions"]) == pytest.approx(math.log(result["equity"][-1]))


def test_no_trigger_cash_window_still_pays_time_hurdle_and_compares_benchmark():
    from src.services.allocation.simulator import simulate_allocation
    from src.services.allocation.fixed_score_policy import FixedScorePolicy
    base, scores = fixture()
    scores.update(buy_signal=[None] * 120, sell_signal=[None] * 120)
    benchmark = BenchmarkSeries({d: 100 for d in base["dates"]}, adjusted=True)
    result = simulate_allocation(base, scores, 0, 119, FixedScorePolicy(), cost_pct_per_side=.1, benchmark=benchmark)
    assert result["equity"][-1] == 1
    assert len(result["transitions"]) == 1
    assert result["economic_summary"]["cagr_penalty"] > 0
    assert result["transitions"][0]["trigger_direction"] == "NEUTRAL"


def test_future_benchmark_cannot_enter_state_or_change_frozen_selection():
    assert not any("benchmark" in f.name or "cagr" in f.name for f in fields(AllocationState))
    base, scores = fixture()
    values = {d: 100 + i * .1 for i, d in enumerate(base["dates"])}
    changed = {d: value * (100 if i >= 96 else 1) for i, (d, value) in enumerate(values.items())}
    config = AllocationConfig.from_dict({"threshold_iterations": 1, "q": {"episodes": 2}})
    def fit(prices):
        return ThresholdStudy(base, scores, (0, 47), (48, 95),
                              dict(cost_pct_per_side=.1, window_days=1, min_trade_gap_bars=1), config,
                              buy_threshold=6, sell_threshold=-6, benchmark=BenchmarkSeries(prices, adjusted=True))
    first, second = fit(values), fit(changed)
    assert first.selected_pair == second.selected_pair
    assert first.selected == second.selected
    assert first.study.policies["Q_LEARNING"].explain() == second.study.policies["Q_LEARNING"].explain()
    before = first.study.policies["Q_LEARNING"].explain()
    first.report((96, 119))
    assert first.study.policies["Q_LEARNING"].explain() == before


@pytest.mark.parametrize("higher_wins", [False, True])
def test_threshold_search_uses_new_rewards_without_mechanical_threshold_bias(higher_wins):
    base, scores = fixture()
    if higher_wins:
        for i in range(48, 96):
            j = (i - 48) % 8
            for key in ("open", "close", "low"):
                base[key][i] = [100, 100, 100, 80, 80, 80, 100, 100][j]
            scores["buy_score"][i] = [0, 5, 0, 0, 6, 0, 0, 0][j]
            scores["sell_score"][i] = [0, 0, 6, 0, 0, 0, 6, 0][j]
    benchmark = BenchmarkSeries({d: 100 * 1.001 ** i for i, d in enumerate(base["dates"])}, adjusted=True)
    study = ThresholdStudy(base, scores, (0, 47), (48, 95),
                           dict(cost_pct_per_side=.1, window_days=1, min_trade_gap_bars=1),
                           AllocationConfig.from_dict({"policy_mode": "CURRENT", "threshold_iterations": 1}),
                           buy_threshold=6, sell_threshold=-6, benchmark=benchmark)
    assert study.selected_pair[0] == (6 if higher_wins else 5)
    for _, rows in study.cache.values():
        for row in rows.values():
            assert all("cagr_penalty" in m and "benchmark_reward" in m for m in row["fold_metrics"])


def test_hard_drawdown_rejection_cannot_be_overridden_by_benchmark_bonus():
    base, scores = fixture()
    scores["buy_score"] = [8 if i % 8 == 0 else 0 for i in range(120)]
    scores["sell_score"] = [0] * 120
    for i in range(120):
        for key in ("open", "close", "low"):
            base[key][i] = 100 if i % 8 < 3 else 30
    benchmark = BenchmarkSeries({d: 100 * .95 ** i for i, d in enumerate(base["dates"])}, adjusted=True)
    config = AllocationConfig.from_dict({"policy_mode": "CURRENT", "threshold_iterations": 1,
                                         "economic": {"allowed_max_drawdown": .05}})
    study = ThresholdStudy(base, scores, (0, 47), (48, 95),
                           dict(cost_pct_per_side=.1, window_days=1, min_trade_gap_bars=1), config,
                           buy_threshold=6, sell_threshold=-6, benchmark=benchmark)
    assert study.selected is None
    report = study.report((96, 119))
    assert report["selection_status"] == "NO_RISK_ELIGIBLE_CANDIDATE"
    assert report["selected_policy"] is None
