"""Staged Strategy G search. Development stress tests precede a frozen final test."""

from dataclasses import replace
from datetime import date
import hashlib
import json
from statistics import median
import subprocess

from src.services.allocation.research import AllocationStudy, allocation_metrics
from src.services.allocation.threshold_research import development_folds, threshold_signals, validation_objective
from src.services.allocation.q_learning_policy import QLearningTrainer
from src.services.allocation.simulator import simulate_allocation
from src.services.allocation.economic_reward import cagr_snapshot
from src.services.strategy_backtester import simulate_buy_hold
from .config import ACESConfig, ACES_VERSION
from .runtime import ACESRuntime, ACESState, ACESStateEncoder, prepare_context


def risk_failures(run, bounds, config, name):
    metrics = allocation_metrics(run, bounds)
    failures = []
    if metrics["risk_rejected"]:
        failures.append("MAX_DRAWDOWN")
    if metrics["turnover"] > config.risk.maximum_turnover:
        failures.append("MAX_TURNOVER")
    if metrics["trade_count"] < config.risk.minimum_trades:
        failures.append("MIN_TRADES")
    if bounds[1] - bounds[0] + 1 < config.risk.minimum_validation_samples:
        failures.append("MIN_SAMPLES")
    if name == "Q_LEARNING" and metrics["fallback_pct"] / 100 > config.risk.maximum_fallback_fraction:
        failures.append("Q_SUPPORT")
    return failures


def require_complete_stock_sessions(base, bounds, benchmark):
    if benchmark is None:
        return  # The shared economic evaluator handles missing-benchmark policy.
    days = base["dates"][bounds[0]:bounds[1] + 1]
    expected = {day for day in benchmark.values if days[0] <= day <= days[-1]}
    if expected - set(days):
        raise ValueError("SYSTEM_SAFE_MODE: missing stock sessions; cannot assume next regular-session execution")


class ACESStudy:
    """No mutation of A–F parameters, Q tables, or validation/test outcomes."""
    def __init__(self, base, scores, train, validation, config=None, benchmark=None, *, metadata=None):
        self.config = config or ACESConfig()
        self.base = prepare_context(base, self.config)
        self.scores, self.benchmark = scores, benchmark
        require_complete_stock_sessions(self.base, (train[0], validation[1]), benchmark)
        self.metadata = dict(metadata or {})
        self.runtime = ACESRuntime(self.config, self.base)
        self.encoder = ACESStateEncoder(self.config, self.base)
        self.execution = self.execution_args(self.config)
        self._reported = False
        folds = development_folds(train, validation, self.config.allocation.validation_folds)
        self.folds = [((tr[0], min(tr[1], va[0] - self.config.purge_bars - 1)), va) for tr, va in folds]
        if any(tr[1] - tr[0] < 252 or va[1] - va[0] + 1 < self.config.risk.minimum_validation_samples
               for tr, va in self.folds):
            raise ValueError("ACES requires sufficient training and validation after the purge gap")
        stage_config = replace(self.config.allocation, policy_mode="FIXED" if self.config.policy_mode == "FIXED" else "TUNED_FIXED")
        self.studies, self.candidates = {}, []
        self.mapping_evaluations = 0
        for buy in self.config.buy_thresholds:
            for sell in self.config.sell_thresholds:
                pair = (buy, sell)
                signals = threshold_signals(self.base, scores, *pair)
                studies = [AllocationStudy(self.base, signals, tr, va, self.execution, stage_config, benchmark,
                                           encoder=self.encoder, runtime=self.runtime) for tr, va in self.folds]
                self.studies[pair] = studies
                self.mapping_evaluations += sum(s.candidates_evaluated for s in studies)
                for name in ("FIXED", "TUNED_FIXED"):
                    if name in studies[0].policies:
                        self.candidates.append(self.candidate(pair, name))
        # Stage 2: Q is trained independently only in promising fixed-policy regions.
        self.q_pairs = []
        if self.config.policy_mode in {"COMPARE", "Q_LEARNING"}:
            promising = sorted(self.candidates, key=lambda r: (bool(r["failures"]), -r["median_return"], -r["score"]))
            for row in promising:
                pair = tuple(row["thresholds"])
                if pair in self.q_pairs:
                    continue
                self.q_pairs.append(pair)
                for study in self.studies[pair]:
                    trainer = QLearningTrainer(study.policies["TUNED_FIXED"], self.config.allocation.q)
                    policy = trainer.train(lambda p, observer: study.simulate(p, study.train, "TRAIN", observer=observer, trace=False))
                    study.policies["Q_LEARNING"] = policy
                    study.training_runs["Q_LEARNING"] = study.simulate(policy, study.train, "TRAIN", trace=False)
                    study.validation_runs["Q_LEARNING"] = study.simulate(policy, study.validation, "VALIDATION", trace=False)
                self.candidates.append(self.candidate(pair, "Q_LEARNING"))
                if len(self.q_pairs) >= self.config.q_finalists:
                    break
        for row in self.candidates:
            buy, sell = row["thresholds"]
            neighbors = [r for r in self.candidates if r["policy"] == row["policy"] and
                         abs(r["thresholds"][0] - buy) + abs(r["thresholds"][1] - sell) == 1]
            row["parameter_stability_score"] = (sum(not r["failures"] and r["median_return"] >=
                row["median_return"] - self.config.stress_return_tolerance for r in neighbors) / len(neighbors)) if neighbors else None
        eligible = [r for r in self.candidates if not r["failures"]]
        if self.config.policy_mode in {"FIXED", "TUNED_FIXED", "Q_LEARNING"}:
            eligible = [r for r in eligible if r["policy"] == self.config.policy_mode]
        profitable = [r for r in eligible if r["median_return"] > 0]
        if profitable:
            eligible = profitable
        elif eligible:
            best = max(r["median_return"] for r in eligible)
            eligible = [r for r in eligible if r["median_return"] >= best - 1e-12]
        self.selected = None
        self.stress_results = []
        # Stage 3/4: prefer simple, broad plateaus in reward near-ties, then stress.
        while eligible:
            best = max(r["score"] for r in eligible)
            near = [r for r in eligible if r["score"] >= best - self.config.allocation.simplicity_tolerance]
            winner = min(near, key=lambda r: (("FIXED", "TUNED_FIXED", "Q_LEARNING").index(r["policy"]),
                                            -(r["parameter_stability_score"] or 0), -r["positive_folds"], r["turnover"]))
            stress = self.stress(winner)
            self.stress_results.append(dict(candidate=winner, scenarios=stress))
            plateau = winner["parameter_stability_score"]
            if all(r["passed"] for r in stress) and plateau is not None and plateau >= self.config.minimum_plateau_fraction:
                self.selected = winner
                break
            eligible.remove(winner)
            # Bounded finalist evaluation, recorded explicitly; never use test to widen it.
            if len(self.stress_results) >= self.config.q_finalists:
                break
        self.inspected = self.selected or max(self.candidates, key=lambda r: (not bool(r["failures"]), r["score"]))

    @staticmethod
    def execution_args(config):
        c = config.execution
        return dict(cost_pct_per_side=c.cost_pct_per_side, window_days=c.buy_spacing_bars,
                    min_trade_gap_bars=c.min_trade_gap_bars, max_entry_gap_atr=c.max_entry_gap_atr,
                    stop_multiple_atr=c.stop_multiple_atr, trail_multiple_atr=c.trail_multiple_atr)

    def candidate(self, pair, name):
        studies = self.studies[pair]
        runs = [s.validation_runs[name] for s in studies]
        scores = [validation_objective(run, va, self.config.allocation.lambda_opportunity)
                  for run, (_, va) in zip(runs, self.folds)]
        returns = [run["equity"][-1] - 1 for run in runs]
        failures = sorted({failure for run, (_, va) in zip(runs, self.folds)
                           for failure in risk_failures(run, va, self.config, name)})
        return dict(thresholds=list(pair), policy=name, score=median(scores) + .1 * min(scores),
                    median_return=median(returns), worst_return=min(returns), positive_folds=sum(r > 0 for r in returns),
                    turnover=median(r["turnover"] for r in runs), failures=failures,
                    fold_metrics=[allocation_metrics(run, va) for run, (_, va) in zip(runs, self.folds)],
                    fitted_targets=[list(getattr(s.policies[name], "fallback", s.policies[name]).targets) for s in studies])

    def run(self, policy, signals, bounds, phase, config=None, trace=True):
        config = config or self.config
        return simulate_allocation(self.base, signals, *bounds, policy, phase=phase, encoder=self.encoder,
                                   runtime=ACESRuntime(config, self.base), benchmark=self.benchmark,
                                   economic_config=config.allocation.economic,
                                   lambda_opportunity=config.allocation.lambda_opportunity,
                                   opportunity_band=config.allocation.opportunity_band,
                                   trace=trace, **self.execution_args(config))

    def stress(self, candidate):
        pair, name = tuple(candidate["thresholds"]), candidate["policy"]
        c = self.config.execution
        scenarios = {
            "BASE": {}, "DOUBLE_COST": {"cost_pct_per_side": min(1., c.cost_pct_per_side * 2)},
            "DOUBLE_SLIPPAGE": {"cost_pct_per_side": min(1., c.cost_pct_per_side + c.slippage_pct), "slippage_pct": c.slippage_pct * 2},
            "DELAY_ONE_DAY": {"delay_bars": 1}, "ENTRY_WORSE_1PCT": {"entry_worsening": .01},
            "EXIT_WORSE_1PCT": {"exit_worsening": .01}, "SKIP_SIGNALS": {"skip_every": 5},
            "NEIGHBOR_BUY_LOWER": {}, "NEIGHBOR_BUY_HIGHER": {},
            "NEIGHBOR_SELL_LOWER": {}, "NEIGHBOR_SELL_HIGHER": {},
            "ALLOCATION_MINUS_20PCT": {}, "ALLOCATION_PLUS_20PCT": {},
        }
        rows = []
        for label, changes in scenarios.items():
            config = replace(self.config, execution=replace(c, **changes))
            metrics, passed = [], True
            for study, (_, va), baseline in zip(self.studies[pair], self.folds, candidate["fold_metrics"]):
                policy, signals = study.policies[name], study.signals
                if label.startswith("NEIGHBOR_"):
                    buy, sell = pair
                    delta = -1 if label.endswith("LOWER") else 1
                    buy, sell = (max(1, buy + delta), sell) if "BUY" in label else (buy, min(-1, sell + delta))
                    # Perturb the frozen policy; do not train Q on validation or reuse it to rank another candidate.
                    signals = threshold_signals(self.base, self.scores, buy, sell)
                if label.startswith("ALLOCATION_"):
                    policy = AllocationPerturbation(policy, -.2 if "MINUS" in label else .2)
                run = self.run(policy, signals, va, "VALIDATION", config, trace=False)
                item = allocation_metrics(run, va)
                failures = risk_failures(run, va, config, name)
                passed &= not failures and item["final_nav"] >= baseline["final_nav"] - self.config.stress_return_tolerance
                metrics.append(dict(metrics=item, failures=failures))
            rows.append(dict(scenario=label, passed=bool(passed), folds=metrics))
        return rows

    def report(self, test):
        if self._reported:
            raise ValueError("ACES final test already evaluated")
        if test[0] - self.folds[-1][1][1] - 1 < self.config.purge_bars or test[1] < test[0]:
            raise ValueError("ACES final test must follow a full purge gap")
        require_complete_stock_sessions(self.base, test, self.benchmark)
        self._reported = True
        pair = tuple(self.inspected["thresholds"])
        study = self.studies[pair][-1]
        rows = []
        report_studies = {name: study for name in study.policies if name != "CURRENT"}
        if "Q_LEARNING" not in report_studies and self.q_pairs:
            q_row = max((r for r in self.candidates if r["policy"] == "Q_LEARNING"),
                        key=lambda r: (not bool(r["failures"]), r["score"]))
            report_studies["Q_LEARNING"] = self.studies[tuple(q_row["thresholds"])][-1]
        for name, policy_study in report_studies.items():
            policy = policy_study.policies[name]
            run = self.run(policy, policy_study.signals, test, "TEST")
            for observation in run["score_observations"]:
                observation["ticker"] = self.metadata.get("ticker")
            test_metrics = allocation_metrics(run, test)
            transitions = run["transitions"]
            decisions = [t for t in transitions if t["trigger_direction"] != "NEUTRAL"]
            trained_states = {key[0] for key in policy.table} if name == "Q_LEARNING" else set()
            test_metrics.update(unseen_state_fraction=sum(ACESState(**t["state_before"]) not in trained_states for t in decisions) / len(decisions)
                                if decisions and name == "Q_LEARNING" else None,
                                regimes_observed=sorted({t["state_before"]["regime"] for t in decisions}),
                                years_tested=test_metrics["elapsed_days"] / 365.25,
                                worst_trade_pct=min((t["return_pct"] for t in run["trades"]), default=None),
                                worst_gap_pct=min((self.base["open"][i] / self.base["close"][i - 1] - 1
                                                   for i in range(test[0] + 1, test[1] + 1)), default=0.) * 100,
                                largest_loss_period=min((t["portfolio_reward"] for t in transitions), default=0.),
                                regime_alpha={regime: sum((t["relative_alpha"] or 0.) for t in transitions
                                              if t["state_before"]["regime"] == regime)
                                              for regime in ("BULL", "BEAR", "SIDEWAYS")})
            rows.append(dict(name=name, thresholds={"buy": policy_study.signals["buy_threshold"], "sell": policy_study.signals["sell_threshold"]},
                             fitted_targets=list(getattr(policy, "fallback", policy).targets),
                             metrics={"train": allocation_metrics(policy_study.training_runs[name], policy_study.train),
                                                 "validation": allocation_metrics(policy_study.validation_runs[name], policy_study.validation),
                                                 "test": test_metrics},
                             transitions=run["transitions"], executions=run["executions"],
                             score_observations=run["score_observations"], economic_curve=run["economic_curve"],
                             test_equity=dict(dates=self.base["dates"][test[0]:test[1] + 1], values=[(n - 1) * 100 for n in run["equity"]]),
                             test_failures=risk_failures(run, test, self.config, name)))
        hold_metrics = {}
        for split, bounds in (("train", study.train), ("validation", study.validation), ("test", test)):
            # Match the strategy/benchmark first-close origin; preserve the shared
            # passive accounting solver and do not alter legacy A–F references.
            opens = list(self.base["open"])
            opens[bounds[0]] = self.base["close"][bounds[0]]
            hold = simulate_buy_hold(dict(self.base, open=opens), *bounds, self.config.execution.cost_pct_per_side)
            elapsed = (date.fromisoformat(self.base["dates"][bounds[1]]) - date.fromisoformat(self.base["dates"][bounds[0]])).days
            hold["economic_summary"] = cagr_snapshot(1., hold["equity"][-1], elapsed, self.config.allocation.economic)
            hold_metrics[split] = allocation_metrics(hold, bounds)
        for row in rows:
            for split, metrics in row["metrics"].items():
                passive = hold_metrics[split]
                metrics.update(return_capture_vs_hold=metrics["total_return_pct"] / passive["total_return_pct"] if passive["total_return_pct"] > 0 else None,
                               drawdown_reduction_pp=abs(passive["max_drawdown_pct"]) - abs(metrics["max_drawdown_pct"]),
                               sharpe_improvement=metrics["sharpe"] - passive["sharpe"],
                               final_budget=self.config.initial_budget * metrics["final_nav"])
            for index, point in enumerate(row["economic_curve"], start=test[0]):
                # Benchmarks are normalized total-return indices; financial B&H
                # metrics above include entry/exit costs separately.
                point["buy_hold_nav"] = self.base["close"][index] / self.base["close"][test[0]]
                days = (date.fromisoformat(point["date"]) - date.fromisoformat(self.base["dates"][test[0]])).days
                point["cash_nav"] = (1 + self.config.execution.cash_yield) ** (days / 365.25)
        selected = next((r for r in rows if self.selected and r["name"] == self.selected["policy"]), None)
        checks = dict(validation_selected=self.selected is not None,
                      positive_validation=bool(self.selected and self.selected["median_return"] > 0),
                      final_test_risk=bool(selected and not selected["test_failures"]),
                      positive_final_test=bool(selected and selected["metrics"]["test"]["total_return_pct"] > 0),
                      benchmark=all(row["metrics"]["test"]["benchmark_status"] == "AVAILABLE" for row in rows),
                      purged=True, frozen=True, stress=bool(self.selected))
        status = "PASS" if all(checks.values()) else "FAIL" if not checks["validation_selected"] or not checks["final_test_risk"] else "WARN"
        config = self.config.to_dict()
        q_study = report_studies.get("Q_LEARNING")
        try:
            commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
            dirty = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=5, check=True).stdout)
        except (OSError, subprocess.SubprocessError):
            commit, dirty = None, None
        frozen_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        source_hashes = {}
        from pathlib import Path
        for folder in (Path(__file__).parent, Path(__file__).parent.parent / "allocation"):
            for path in sorted(folder.glob("*.py")):
                source_hashes[f"{folder.name}/{path.name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
        return dict(strategy_key="G", name="ACES — Adaptive Capital Efficiency Strategy", version=ACES_VERSION,
                    selected_policy=self.selected["policy"] if self.selected else None,
                    selection_basis="purged_walk_forward_then_stress", selection_status="SELECTED" if self.selected else "NO_RISK_ELIGIBLE_CANDIDATE",
                    config=config, policies=rows, selected_thresholds=dict(buy=pair[0], sell=pair[1]),
                    inspected_only=self.selected is None, readiness=dict(status=status, checks=checks),
                    test_risk_status=("NOT_SELECTED" if selected is None else "BREACH" if selected["metrics"]["test"]["risk_rejected"]
                                      else "FAILED_CHECKS" if selected["test_failures"] else "PASSED"),
                    benchmark_status=rows[0]["metrics"]["test"]["benchmark_status"],
                    q_table=[r for r in q_study.policies["Q_LEARNING"].explain() if r["valid_at_bucket"]] if q_study else [],
                    unique_states_visited=len({key[0] for key in q_study.policies["Q_LEARNING"].table}) if q_study else 0,
                    candidates=self.candidates, robustness=self.stress_results,
                    parameter_stability_score=self.inspected["parameter_stability_score"],
                    folds=[dict(train_dates=[self.base["dates"][tr[0]], self.base["dates"][tr[1]]],
                                validation_dates=[self.base["dates"][va[0]], self.base["dates"][va[1]]],
                                purge_bars=va[0] - tr[1] - 1) for tr, va in self.folds],
                    test_dates=[self.base["dates"][test[0]], self.base["dates"][test[1]]], buy_hold_metrics=hold_metrics,
                    search_complexity=dict(technical_candidates=1, threshold_combinations=len(self.studies),
                                           allocation_maps_evaluated=self.mapping_evaluations, q_hyperparameter_sets=1,
                                           q_regions=len(self.q_pairs), total_candidates=len(self.candidates)),
                    provenance=dict(**self.metadata, git_commit=commit, working_tree_dirty=dirty, config_hash=frozen_hash, source_hashes=source_hashes,
                                    benchmark_data_hash=hashlib.sha256(json.dumps(dict(self.benchmark.values), sort_keys=True).encode()).hexdigest() if self.benchmark else None,
                                    data_hash=hashlib.sha256(json.dumps({k: self.base[k] for k in ("dates", "open", "high", "low", "close", "volume")}, sort_keys=True).encode()).hexdigest()),
                    live_enabled=False, live_status="SYSTEM_SAFE_MODE: research policy is not installed for live trading")


class AllocationPerturbation:
    learning = False

    def __init__(self, policy, delta):
        self.policy, self.delta = policy, delta

    def choose(self, state, trigger, portfolio):
        decision = self.policy.choose(state, trigger, portfolio)
        if decision.target is None:
            return decision
        target = min(1., max(0., decision.target + self.delta))
        if trigger.direction == "BUY":
            target = max(target, portfolio.current_exposure)
        else:
            target = min(target, portfolio.current_exposure)
        return replace(decision, target=target)
