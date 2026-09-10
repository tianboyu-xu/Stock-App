"""Train-only policy fitting, validation selection, and frozen report-only testing."""

from dataclasses import asdict, dataclass
import math

from .allocation_state import StateConfig, StateEncoder
from .fixed_score_policy import CurrentAllocationPolicy, FixedScorePolicy
from .q_learning_policy import QConfig, QLearningTrainer
from .simulator import simulate_allocation
from .tuned_fixed_policy import tune_fixed
from .economic_reward import EconomicConfig

POLICY_ORDER = ("CURRENT", "FIXED", "TUNED_FIXED", "Q_LEARNING")


@dataclass(frozen=True)
class AllocationConfig:
    policy_mode: str = "AUTO"
    simplicity_tolerance: float = .01  # validation cumulative log-return units
    q: QConfig = QConfig()
    state: StateConfig = StateConfig()
    lambda_opportunity: float = .25
    opportunity_band: float = 2.0
    threshold_iterations: int = 2
    validation_folds: int = 3
    economic: EconomicConfig = EconomicConfig()

    def __post_init__(self):
        if self.policy_mode not in (*POLICY_ORDER, "AUTO"):
            raise ValueError("unknown allocation policy mode")
        if not math.isfinite(self.simplicity_tolerance) or self.simplicity_tolerance < 0:
            raise ValueError("simplicity_tolerance must be nonnegative and finite")
        if not math.isfinite(self.lambda_opportunity) or not 0 <= self.lambda_opportunity <= .5:
            raise ValueError("lambda_opportunity must be in [0, .5]")
        if not math.isfinite(self.opportunity_band) or not 0 < self.opportunity_band <= 5:
            raise ValueError("opportunity_band must be in (0, 5]")
        if type(self.threshold_iterations) is not int or not 1 <= self.threshold_iterations <= 3:
            raise ValueError("threshold_iterations must be an integer in [1, 3]")
        if type(self.validation_folds) is not int or not 2 <= self.validation_folds <= 5:
            raise ValueError("validation_folds must be an integer in [2, 5]")

    @classmethod
    def from_dict(cls, values=None):
        if values is not None and not isinstance(values, dict):
            raise ValueError("allocation configuration must be an object")
        values = dict(values or {})
        try:
            values["q"] = QConfig(**values.get("q", {}))
            values["state"] = StateConfig(**values.get("state", {}))
            values["economic"] = EconomicConfig(**values.get("economic", {}))
            return cls(**values)
        except TypeError as error:
            raise ValueError(f"Invalid allocation configuration: {error}") from error


def select_policy(validation_scores, tolerance):
    validation_scores = {name: score for name, score in validation_scores.items() if score is not None}
    if not validation_scores:
        return None
    best = max(validation_scores.values())
    return next(name for name in POLICY_ORDER if name in validation_scores and validation_scores[name] >= best - tolerance)


def allocation_metrics(simulation, bounds):
    from src.services.strategy_backtester import summarize_metrics
    metrics = summarize_metrics(simulation, *bounds)
    # The legacy per-round-trip tax approximation is not valid for partial sales.
    # Allocation comparisons deliberately expose pre-tax, after-trading-cost metrics.
    metrics.pop("after_tax_total_return_pct")
    metrics.pop("after_tax_cagr_pct")
    metrics.update(initial_nav=simulation["initial_equity"], final_nav=simulation["equity"][-1],
                   closed_trade_count=len(simulation["trades"]), trade_count=simulation["trade_count"],
                   turnover=simulation["turnover"], average_exposure_pct=simulation["average_exposure"] * 100,
                   transaction_cost=simulation["transaction_cost"],
                   allocation_decisions=simulation.get("allocation_decisions", 0),
                   budget_constrained_decisions=simulation.get("budget_constrained_decisions", 0),
                   low_sample_fallbacks=simulation.get("low_sample_fallbacks", 0),
                   fallback_pct=100 * simulation.get("low_sample_fallbacks", 0) / max(1, simulation.get("allocation_decisions", 0)))
    for key in ("opportunity_regret", "missed_upside_regret", "missed_downside_regret", "learning_reward",
                "threshold_upside_regret", "threshold_downside_regret",
                "missed_upside_count", "missed_downside_count",
                "threshold_missed_buy_count", "threshold_missed_sell_count"):
        metrics[key] = simulation.get(key, 0.)
    metrics["average_opportunity_regret"] = metrics["opportunity_regret"] / max(1, metrics["allocation_decisions"])
    metrics["cash_utilization_pct"] = 100 - metrics["average_exposure_pct"]
    gain = max(0., metrics["final_nav"] - 1.)
    missed = math.expm1(metrics["missed_upside_regret"])
    metrics["opportunity_capture_ratio"] = gain / (gain + missed) if gain + missed > 0 else None
    metrics.update(simulation.get("economic_summary", {}))
    return metrics


class AllocationStudy:
    """A staged allocation experiment on one already-frozen technical strategy.

    Technical search uses the current allocation reference. Allocation fitting sees
    only its training range; no test range is accepted until report() is called.
    """

    def __init__(self, base, signals, train, validation, execution, config=None, benchmark=None,
                 *, encoder=None, runtime=None):
        if not (0 <= train[0] <= train[1] < validation[0] <= validation[1] < len(base["close"])):
            raise ValueError("allocation train/validation ranges must be ordered and non-overlapping")
        self.base, self.signals = base, signals
        self.train, self.validation = train, validation
        self.execution = execution
        self.config = config or AllocationConfig()
        self.benchmark = benchmark
        self.encoder = encoder or StateEncoder(self.config.state)
        self.runtime = runtime
        current = CurrentAllocationPolicy(signals.get("buy_allocation", [1.] * len(base["close"])),
                                          execution["cost_pct_per_side"] / 100)
        self.policies = {"CURRENT": current, "FIXED": FixedScorePolicy()}
        mode = self.config.policy_mode
        self.candidates_evaluated = 0
        if mode in {"AUTO", "TUNED_FIXED", "Q_LEARNING"}:
            tuned, self.candidates_evaluated = tune_fixed(
                lambda p: self.score(self.simulate(p, train, "TRAIN", trace=False)))
            self.policies["TUNED_FIXED"] = tuned
            if mode in {"AUTO", "Q_LEARNING"}:
                trainer = QLearningTrainer(tuned, self.config.q)
                self.policies["Q_LEARNING"] = trainer.train(
                    lambda policy, observer: self.simulate(policy, train, "TRAIN", observer=observer, trace=False))
        if mode == "CURRENT":
            self.policies = {"CURRENT": current}
        self.training_runs = {name: self.simulate(p, train, "TRAIN", trace=False) for name, p in self.policies.items()}
        self.validation_runs = {name: self.simulate(p, validation, "VALIDATION", trace=False) for name, p in self.policies.items()}
        self.validation_scores = {name: None if run["economic_summary"]["risk_rejected"] else self.score(run)
                                  for name, run in self.validation_runs.items()}
        self.selected = select_policy(self.validation_scores, self.config.simplicity_tolerance)
        self._reported = False

    def score(self, run):
        return (math.log(run["equity"][-1]) - self.config.lambda_opportunity * run["opportunity_regret"]
                + run["economic_summary"]["benchmark_reward"] - run["economic_summary"]["cagr_penalty"])

    def simulate(self, policy, bounds, phase, **kwargs):
        if (getattr(policy, "learning", False) or kwargs.get("observer") is not None) and tuple(bounds) != tuple(self.train):
            raise ValueError("learning is restricted to this study's training range")
        return simulate_allocation(self.base, self.signals, *bounds, policy, encoder=self.encoder,
                                   phase=phase, lambda_opportunity=self.config.lambda_opportunity,
                                   economic_config=self.config.economic, benchmark=self.benchmark,
                                   runtime=self.runtime,
                                   opportunity_band=self.config.opportunity_band, **self.execution, **kwargs)

    def report(self, test):
        if self._reported:
            raise ValueError("final test has already been evaluated for this fitted study")
        if not self.validation[1] < test[0] <= test[1] < len(self.base["close"]):
            raise ValueError("final test must follow validation")
        self._reported = True
        test_runs = {name: self.simulate(policy, test, "TEST") for name, policy in self.policies.items()}
        from src.services.strategy_backtester import simulate_buy_hold
        hold_runs = {key: simulate_buy_hold(self.base, *bounds, self.execution["cost_pct_per_side"])
                     for key, bounds in (("train", self.train), ("validation", self.validation), ("test", test))}
        # The passive reference uses the same calendar CAGR maturity convention.
        # It has no policy transitions, so do not invent reward/regret attribution.
        from datetime import date
        from .economic_reward import cagr_snapshot
        for key, bounds in (("train", self.train), ("validation", self.validation), ("test", test)):
            elapsed = (date.fromisoformat(self.base["dates"][bounds[1]])
                       - date.fromisoformat(self.base["dates"][bounds[0]])).days
            hold_runs[key]["economic_summary"] = cagr_snapshot(
                1., hold_runs[key]["equity"][-1], elapsed, self.config.economic)
        rows = [dict(name="BUY_HOLD", metrics={key: allocation_metrics(hold_runs[key], bounds)
                    for key, bounds in (("train", self.train), ("validation", self.validation), ("test", test))},
                     transitions=[], executions=[], test_equity={"dates": self.base["dates"][test[0]:test[1] + 1],
                     "values": [(v - 1) * 100 for v in hold_runs["test"]["equity"]]})]
        for name, run in test_runs.items():
            rows.append(dict(name=name, metrics={
                "train": allocation_metrics(self.training_runs[name], self.train),
                "validation": allocation_metrics(self.validation_runs[name], self.validation),
                "test": allocation_metrics(run, test)}, transitions=run["transitions"], executions=run["executions"],
                trigger_signature=run["trigger_signature"],
                score_observations=run["score_observations"],
                economic_curve=run["economic_curve"],
                test_equity={"dates": self.base["dates"][test[0]:test[1] + 1], "values": [(v - 1) * 100 for v in run["equity"]]}))
        return dict(selected_policy=self.selected, selection_basis="validation_economic_reward",
                    benchmark_status=self.validation_runs["CURRENT"]["economic_summary"]["benchmark_status"],
                    selection_status="SELECTED" if self.selected is not None else "NO_RISK_ELIGIBLE_CANDIDATE",
                    config=asdict(self.config), validation_scores=self.validation_scores,
                    policies=rows, unique_states_visited=len({key[0] for key in self.policies["Q_LEARNING"].table})
                    if "Q_LEARNING" in self.policies else 0,
                    q_table=self.policies["Q_LEARNING"].explain() if "Q_LEARNING" in self.policies else [],
                    tuned_fixed_targets=list(self.policies["TUNED_FIXED"].targets) if "TUNED_FIXED" in self.policies else None)
