"""Regression coverage for chronological selection and untouched final tests.

Search budgets are small; indicators, objective, execution, costs and metrics all
run for real. Spies observe selection/simulation boundaries without replacing
the calculations that could leak held-out prices into recommendations.
"""

import copy
import math
import random
from datetime import date, timedelta
from statistics import median, pstdev

import pytest

from src.services import indicator_optimizer as optimizer


def _bars(count):
    result = []
    for index in range(count):
        close = 100 + 0.02 * index + 9 * math.sin(index / 10) + 3 * math.sin(index / 3)
        result.append({
            "date": (date(2014, 1, 1) + timedelta(days=index)).isoformat(),
            "open": close * (1 + 0.002 * math.sin(index)),
            "high": close + 1, "low": close - 1, "close": close,
            "volume": 1_000_000 * (1.5 + 0.4 * math.sin(index / 7)),
        })
    return result


@pytest.fixture(autouse=True)
def _small_search(monkeypatch):
    monkeypatch.setattr(optimizer, "SAMPLED_CANDIDATES", 3)
    monkeypatch.setattr(optimizer, "HILL_CLIMB_SEEDS", 1)
    monkeypatch.setattr(optimizer, "HILL_CLIMB_SWEEPS", 0)
    monkeypatch.setattr(optimizer, "TOP_K", 4)


def test_aces_is_opt_in_and_preserves_all_legacy_generations():
    from src.services.allocation.economic_reward import BenchmarkSeries
    bars = _bars(1300)
    benchmark = BenchmarkSeries({b["date"]: 100 + i * .01 for i, b in enumerate(bars)}, adjusted=True)
    kwargs = dict(window_days=20, test_years=1, seed=19,
                  allocation_config={"policy_mode": "CURRENT", "threshold_iterations": 1},
                  allocation_benchmark=benchmark)
    legacy = optimizer.run_auto_tune(bars, **kwargs)
    expanded = optimizer.run_auto_tune(bars, **kwargs, aces_config={
        "policy_mode": "FIXED", "buy_thresholds": [5, 6], "sell_thresholds": [-5, -6], "purge_bars": 20,
        "allocation": {"validation_folds": 2}, "risk": {"minimum_trades": 1}},
        aces_metadata={"ticker": "SYNTH", "adjustment_mode": "ADJUSTED_TOTAL_RETURN"})
    assert legacy["aces"] is None
    assert expanded["strategies"] == legacy["strategies"]
    assert expanded["recommended"] == legacy["recommended"]
    assert expanded["allocation"] == legacy["allocation"]
    assert expanded["aces"]["strategy_key"] == "G"
    assert expanded["aces"]["version"] == 1
    assert not expanded["aces"]["live_enabled"]
    assert expanded["aces"]["policies"][0]["economic_curve"][0]["buy_hold_nav"] == 1


def test_aces_reserves_validation_before_default_purge_without_touching_test():
    from src.services.allocation.economic_reward import BenchmarkSeries
    bars = _bars(1800)
    benchmark = BenchmarkSeries({b["date"]: 100 + i * .01 for i, b in enumerate(bars)}, adjusted=True)
    report = optimizer.run_auto_tune(
        bars, window_days=20, test_years=1, seed=19, allocation_benchmark=benchmark,
        allocation_config={"policy_mode": "CURRENT", "threshold_iterations": 1},
        aces_config={"policy_mode": "FIXED", "buy_thresholds": [6], "sell_thresholds": [-6]})
    aces = report["aces"]
    assert "error" not in aces
    assert aces["test_dates"][0] == report["split"]["test"]["start_date"]
    date_indices = {bar["date"]: i for i, bar in enumerate(bars)}
    assert len(aces["folds"]) == 3
    for fold in aces["folds"]:
        assert fold["purge_bars"] >= 252
        start, end = map(date_indices.get, fold["validation_dates"])
        assert end - start + 1 >= 40
    validation_end = date_indices[aces["folds"][-1]["validation_dates"][1]]
    assert date_indices[aces["test_dates"][0]] - validation_end - 1 == 252
    assert report["test_prices"]["dates"][0] == aces["test_dates"][0]
    assert report["test_prices"]["values"][0] == bars[date_indices[aces["test_dates"][0]]]["close"]


@pytest.mark.parametrize("history,with_benchmark", [(1800, False), (900, True)])
def test_aces_unavailable_research_still_returns_fixed_rule_backtest(history, with_benchmark):
    from src.services.allocation.economic_reward import BenchmarkSeries
    bars = _bars(history)
    benchmark = BenchmarkSeries({b["date"]: 100 + i * .01 for i, b in enumerate(bars)}, adjusted=True) if with_benchmark else None
    report = optimizer.run_auto_tune(
        bars, window_days=20, test_years=1, seed=19, allocation_benchmark=benchmark,
        allocation_config={"policy_mode": "CURRENT", "threshold_iterations": 1},
        aces_config={"policy_mode": "FIXED", "buy_thresholds": [5, 6], "sell_thresholds": [-5, -6]})
    aces = report["aces"]
    assert "error" not in aces
    assert aces["simulation_status"] == "COMPLETED"
    assert aces["simulation_mode"] == "PRESET"
    assert aces["research_status"] == "UNAVAILABLE"
    assert aces["warnings"]
    row = aces["policies"][0]
    assert row["thresholds"] == {"buy": 6, "sell": -6}
    assert row["metrics"]["train"] is None and row["metrics"]["validation"] is None
    assert row["test_equity"]["dates"] == report["test_prices"]["dates"]
    assert len(row["economic_curve"]) == len(report["test_prices"]["dates"])
    assert row["executions"]
    assert all(0 <= fill["holding_pct"] <= 100 for fill in row["executions"])
    assert row["metrics"]["test"]["final_nav"] > 0
    if not with_benchmark:
        assert all(point["benchmark_nav"] is None for point in row["economic_curve"])
    assert not aces["live_enabled"]


def test_aces_invalid_prices_are_not_disguised_as_a_completed_backtest():
    bars = _bars(900)
    bars[500]["low"] = bars[500]["high"] + 5
    report = optimizer.run_auto_tune(
        bars, window_days=20, test_years=1, seed=19,
        allocation_config={"policy_mode": "CURRENT", "threshold_iterations": 1}, aces_config={"enabled": True})
    assert report["aces"]["simulation_status"] == "UNAVAILABLE"
    assert "OHLC" in report["aces"]["error"]


def test_holdout_perturbation_cannot_change_any_selected_window_strategy_or_parameter():
    bars = _bars(1300)
    bounds = optimizer._split_ranges(len(bars), test_bars=252)
    changed = copy.deepcopy(bars)
    for index in range(bounds["test"][0], len(bars)):
        factor = 0.3 + 2.0 * (index - bounds["test"][0]) / 252
        for key in ("open", "high", "low", "close"):
            changed[index][key] *= factor
        changed[index]["volume"] *= 5

    kwargs = dict(window_days=20, test_years=1, fine_tune_window_days=450, seed=19,
                  allocation_config={"q": {"episodes": 3}, "threshold_iterations": 1})
    original = optimizer.run_auto_tune(bars, **kwargs)
    perturbed = optimizer.run_auto_tune(changed, **kwargs)
    assert original["recommended"] == perturbed["recommended"]
    assert len(original["walk_forward"]["folds"]) == 3
    assert original["walk_forward"] == perturbed["walk_forward"]
    for key in ("selected_policy", "validation_scores", "q_table", "tuned_fixed_targets", "config", "joint_thresholds"):
        assert original["allocation"][key] == perturbed["allocation"][key]
        assert original["fine_tune"]["final_test"]["allocation"][key] == perturbed["fine_tune"]["final_test"]["allocation"][key]
    for before, after in zip(original["strategies"], perturbed["strategies"]):
        assert before["params"] == after["params"]
        assert before["validation_folds"] == after["validation_folds"]
        assert before["validation_score"] == after["validation_score"]

    before = original["fine_tune"]
    after = perturbed["fine_tune"]
    assert before["selection_basis"] == "validation"
    assert before["positions_tested"] > 1
    assert before["sweep"] == after["sweep"]
    assert before["best_position_index"] == after["best_position_index"]
    assert before["final_test"]["strategy_key"] == after["final_test"]["strategy_key"]
    assert before["final_test"]["position_index"] == after["final_test"]["position_index"]
    assert before["final_test"]["metrics"] != after["final_test"]["metrics"]
    for row in before["sweep"]:
        for result in [row, *row["all_strategies"]]:
            assert all(result[key] is None for key in ("test_cagr", "test_sharpe", "test_max_dd", "test_trades"))
            assert all(result[key] is not None for key in (
                "validation_cagr", "validation_sharpe", "validation_max_dd", "validation_trades", "validation_score",
            ))


def test_all_selection_finishes_before_test_and_only_one_fine_tune_winner_is_simulated(monkeypatch):
    bars = _bars(1000)
    test_range = optimizer._split_ranges(len(bars), test_bars=252)["test"]
    actual_simulate = optimizer.simulate_trades
    actual_search = optimizer._search_generation
    actual_sweep = optimizer._fine_tune_search
    actual_simplest = optimizer._simplest_generation
    state = {"frozen": False, "test_started": False}
    test_calls = []
    chosen_generations = []

    def search(evaluator, gen, train, validation, rng):
        assert not state["test_started"]
        assert train[1] < validation[0] <= validation[1] < test_range[0]
        # Searches for another fold/generation/window must release the previous
        # candidates' length-n signal arrays before allocating a new pool.
        assert not evaluator._signal_cache
        return actual_search(evaluator, gen, train, validation, rng)

    def simplest(scores):
        assert not state["test_started"]
        selected = actual_simplest(scores)
        chosen_generations.append(selected)
        return selected

    def sweep(*args, **kwargs):
        assert not state["test_started"]
        result = actual_sweep(*args, **kwargs)
        state["frozen"] = True
        return result

    def simulate(base, signals, start, end, *args, **kwargs):
        if (start, end) == test_range:
            assert state["frozen"]
            state["test_started"] = True
            # Benchmark replay has a different price path; count stock tests only.
            if base["close"][0] == bars[0]["close"]:
                test_calls.append((start, end))
        return actual_simulate(base, signals, start, end, *args, **kwargs)

    monkeypatch.setattr(optimizer, "_search_generation", search)
    monkeypatch.setattr(optimizer, "_simplest_generation", simplest)
    monkeypatch.setattr(optimizer, "_fine_tune_search", sweep)
    monkeypatch.setattr(optimizer, "simulate_trades", simulate)
    benchmark = copy.deepcopy(bars)
    for bar in benchmark:
        for key in ("open", "high", "low", "close"):
            bar[key] *= 2
    report = optimizer.run_auto_tune(
        bars, window_days=20, test_years=1, fine_tune_window_days=280,
        benchmark_bars=benchmark, allocation_config={"q": {"episodes": 3}, "threshold_iterations": 1},
    )
    assert report["recommended"]["strategy_key"] == chosen_generations[0]
    assert len(test_calls) == len(optimizer.GENERATIONS) + 1
    assert len(chosen_generations) == report["fine_tune"]["positions_tested"] + 1


def test_walk_forward_is_chronological_aggregates_dispersion_and_uses_latest_params(monkeypatch):
    searches = {}
    actual_search = optimizer._search_generation

    def search(evaluator, gen, train, validation, rng):
        result = actual_search(evaluator, gen, train, validation, rng)
        searches[(gen["key"], train, validation)] = copy.deepcopy(result[0])
        return result

    monkeypatch.setattr(optimizer, "_search_generation", search)
    bars = _bars(1300)
    report = optimizer.run_auto_tune(bars, window_days=20, test_years=1,
                                     allocation_config={"q": {"episodes": 3}, "threshold_iterations": 1})
    folds = report["walk_forward"]["folds"]
    assert len(folds) == 3
    assert folds[-1]["train"] == report["split"]["train"]
    assert folds[-1]["validation"] == report["split"]["validation"]
    for index, fold in enumerate(folds):
        assert fold["train"]["end_date"] < fold["validation"]["start_date"]
        assert fold["validation"]["end_date"] < report["split"]["test"]["start_date"]
        if index:
            assert folds[index - 1]["validation"]["end_date"] < fold["validation"]["start_date"]

    bounds = optimizer._split_ranges(len(bars), test_bars=252)
    for strategy in report["strategies"]:
        scores = [fold["score"] for fold in strategy["validation_folds"]]
        assert strategy["validation_score"] == pytest.approx(median(scores) - pstdev(scores))
        assert strategy["validation_positive_folds"] == sum(
            fold["metrics"]["cagr_pct"] > 0 for fold in strategy["validation_folds"]
        )
        assert strategy["validation_eligible_folds"] == sum(score > -1e5 for score in scores)
        if strategy["tuned"]:
            candidate = searches[(strategy["key"], bounds["train"], bounds["validation"])]
            assert strategy["params"]["thresholds"] == optimizer._chart_thresholds(candidate)


def test_short_or_clipped_history_does_not_invent_short_extra_folds():
    train = (600, 750)
    validation = (900, 1100)
    assert optimizer._walk_forward_folds(train, validation, 90) == [{"train": train, "validation": validation}]
    folds = optimizer._walk_forward_folds((220, 1320), (1400, 1680), 90)
    assert all(fold["train"][0] == 220 for fold in folds)
    assert all(fold["validation"][1] <= 1320 for fold in folds[:-1])
    assert folds[-1]["train"] == (220, 1320)


def test_fine_tune_folds_use_common_validation_and_expand_only_into_past_data():
    validation = (1800, 2639)
    first = optimizer._walk_forward_folds((220, 1100), validation, 90, within_validation=True)
    shifted = optimizer._walk_forward_folds((400, 1280), validation, 90, within_validation=True)
    assert len(first) == 3
    assert [fold["validation"] for fold in first] == [fold["validation"] for fold in shifted]
    for folds in (first, shifted):
        for index, fold in enumerate(folds):
            assert fold["train"][1] < fold["validation"][0]
            assert fold["validation"][1] - fold["validation"][0] + 1 >= 270
            if index:
                assert fold["train"][1] == folds[index - 1]["validation"][1]


def test_top_k_includes_random_candidates_and_deduplicates_hill_results(monkeypatch):
    monkeypatch.setattr(optimizer, "SAMPLED_CANDIDATES", 9)
    monkeypatch.setattr(optimizer, "HILL_CLIMB_SEEDS", 3)
    monkeypatch.setattr(optimizer, "TOP_K", 8)
    candidates = []
    for index in range(9):
        values = optimizer._default_tunable(optimizer.CLASSIC_TUNABLE_KEYS)
        values["composite_buy_threshold"] = optimizer.TUNABLE_GRID["composite_buy_threshold"][index % 5]
        values["composite_sell_threshold"] = optimizer.TUNABLE_GRID["composite_sell_threshold"][index // 5]
        candidates.append(values)
    remaining = iter(candidates)
    monkeypatch.setattr(optimizer, "_sample_tunable", lambda rng, scope: next(remaining))
    evaluator = optimizer._GenerationEvaluator(optimizer.prepare_base_series(_bars(1200)), 20, 0.1)
    actual_evaluate = evaluator.evaluate
    validated = []

    def evaluate(thresholds, start, end, gen, stop, trail):
        result = actual_evaluate(thresholds, start, end, gen, stop, trail)
        if start == 850:
            validated.append((tuple(sorted(thresholds.items())), result[1]))
        return result

    monkeypatch.setattr(evaluator, "evaluate", evaluate)
    _, score, robustness = optimizer._search_generation(
        evaluator, optimizer.GENERATIONS[1], (220, 849), (850, 1199), random.Random(7),
    )
    assert len(validated) == 8
    assert len({item[0] for item in validated}) == 8
    assert score == max(item[1] for item in validated)
    assert robustness == sum(item[1] >= score - optimizer.EPS_SIMPLICITY for item in validated) / 8


def test_minimum_history_is_checked_after_requested_trim():
    with pytest.raises(ValueError, match="裁剪历史后"):
        optimizer.run_auto_tune(_bars(760), history_years=1)


@pytest.mark.parametrize("initial", [None, 2.0])
def test_equity_chart_keeps_opening_cost_and_first_day_return(initial):
    simulation = {"equity": [0.99, 1.1]}
    if initial is not None:
        simulation["initial_equity"] = initial
    series = optimizer._equity_series({"dates": ["first", "last"]}, simulation, 0, 1)
    assert series["values"] == pytest.approx([(value / (initial or 1) - 1) * 100 for value in simulation["equity"]])


@pytest.mark.parametrize("coverage", ["both", "train_only", "test_only"])
def test_benchmark_cash_and_missing_segments_never_return_training_equity_as_test(coverage):
    bars = _bars(900)
    base = optimizer.prepare_base_series(bars)
    ranges = optimizer._split_ranges(len(bars), test_bars=252)
    evaluator = optimizer._GenerationEvaluator(base, 20, 0.1)
    thresholds = {"composite_buy_threshold": 999}
    gen = optimizer.GENERATIONS[0]
    test = evaluator.simulate(thresholds, *ranges["test"], gen)
    benchmark = bars
    if coverage == "train_only":
        benchmark = bars[:ranges["test"][0]]
    elif coverage == "test_only":
        benchmark = bars[ranges["test"][0]:]
    report = optimizer._build_benchmarks(
        base, ranges, evaluator, thresholds, gen, None, None, 20, 0.1, 35, 15,
        benchmark, recommended_test_simulation=test,
    )
    entry = next(item for item in report if item["key"] == "strategy_on_sp500")
    assert entry["available"]
    if coverage == "train_only":
        assert entry["metrics"]["test"] is None
        assert entry["test_equity"] is None
    else:
        assert entry["metrics"]["test"]["trades"] == 0
        assert entry["test_equity"]["dates"] == base["dates"][ranges["test"][0]:]
        assert entry["test_equity"]["values"] == [0] * 252
        if coverage == "test_only":
            assert entry["metrics"]["train_validation"] is None
