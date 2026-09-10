"""Bounded joint threshold/allocation search; final test is outside the search."""

import math
from statistics import median, pstdev

from src.services.strategy_scoring import signal_enter
from .research import AllocationStudy, POLICY_ORDER, allocation_metrics


def threshold_signals(base, scores, buy_threshold, sell_threshold):
    """Reuse cached scores; engine uses positive SELL magnitude internally."""
    if not (0 < buy_threshold and sell_threshold < 0):
        raise ValueError("BUY threshold must be positive and SELL negative")
    result = dict(scores)
    buys, sells = [], []
    for i, (buy, sell) in enumerate(zip(scores["buy_score"], scores["sell_score"])):
        b, s = signal_enter(scores["buy_score"][i - 1] if i else 0, buy,
                            scores["sell_score"][i - 1] if i else 0, sell,
                            buy_threshold, -sell_threshold)
        buys.append(base["close"][i] if b else None)
        sells.append(base["close"][i] if s else None)
    result.update(buy_signal=buys, sell_signal=sells,
                  buy_threshold=buy_threshold, sell_threshold=sell_threshold)
    return result


def development_folds(train, validation, count):
    length = validation[1] - validation[0] + 1
    if length < count:
        raise ValueError("insufficient validation bars for multiple allocation folds")
    folds = []
    for i in range(count):
        start = validation[0] + length * i // count
        end = validation[0] + length * (i + 1) // count - 1
        folds.append((train if i == 0 else (train[0], start - 1), (start, end)))
    return folds


def validation_objective(run, bounds, opportunity_weight):
    metrics = allocation_metrics(run, bounds)
    # All terms share fractional/log-return scales; actual return remains primary.
    return (math.log(metrics["final_nav"]) - opportunity_weight * metrics["opportunity_regret"]
            + metrics.get("benchmark_reward", 0.) - metrics.get("cagr_penalty", 0.)
            - .1 * abs(metrics["max_drawdown_pct"]) / 100 - .001 * metrics["turnover"])


class ThresholdStudy:
    """Each (threshold pair, fold) owns a fresh independently trained policy set.

    Indicator/factor parameters are fixed at the caller's technical seed. The
    outer search jointly selects trigger thresholds and allocation; no universal
    Q table or final-test metrics are reused across candidates.
    """

    def __init__(self, base, scores, train, validation, execution, config, *, buy_threshold, sell_threshold, benchmark=None):
        self.base, self.config = base, config
        self.original = (int(buy_threshold), int(sell_threshold))
        self.folds = development_folds(train, validation, config.validation_folds)
        self.cache = {}
        self._reported = False
        center = self.original
        # Score maxima are derived solely from development data, never final test.
        maximum = max(8, *scores["buy_score"][train[0]:validation[1] + 1],
                      *scores["sell_score"][train[0]:validation[1] + 1], abs(center[1]), center[0])

        def fit(pair):
            if pair not in self.cache:
                signals = threshold_signals(base, scores, *pair)
                studies = [AllocationStudy(base, signals, tr, va, execution, config, benchmark) for tr, va in self.folds]
                rows = {}
                for name in studies[0].policies:
                    runs = [study.validation_runs[name] for study in studies]
                    scores_ = [validation_objective(run, va, config.lambda_opportunity)
                               for run, (_, va) in zip(runs, self.folds)]
                    returns = [run["equity"][-1] - 1 for run in runs]
                    rows[name] = dict(score=median(scores_) + .1 * min(scores_),
                                      risk_rejected=any(run["economic_summary"]["risk_rejected"] for run in runs),
                                      median_validation_return=median(returns), worst_validation_return=min(returns),
                                      positive_folds=sum(r > 0 for r in returns),
                                      median_validation_regret=median(r["opportunity_regret"] for r in runs),
                                      median_turnover=median(r["turnover"] for r in runs),
                                      median_trade_count=median(r["trade_count"] for r in runs),
                                      fold_scores=scores_, fold_metrics=[allocation_metrics(run, va)
                                      for run, (_, va) in zip(runs, self.folds)])
                self.cache[pair] = (studies, rows)
            return self.cache[pair]

        fit(center)
        selected = (center, "CURRENT")
        self.iterations = 0
        for _ in range(config.threshold_iterations):
            self.iterations += 1
            for buy in range(max(1, center[0] - 1), min(int(maximum), center[0] + 1) + 1):
                for sell in range(max(-int(maximum), center[1] - 1), min(-1, center[1] + 1) + 1):
                    fit((buy, sell))
            choices = [(pair, name, row) for pair, (_, rows) in self.cache.items() for name, row in rows.items()
                       if not row["risk_rejected"]]
            if not choices:
                selected = (self.original, None)
                break
            # Relative rewards cannot promote a losing candidate over profitable ones.
            profitable = [item for item in choices if item[2]["median_validation_return"] > 0]
            if profitable:
                choices = profitable
            else:
                best_return = max(item[2]["median_validation_return"] for item in choices)
                choices = [item for item in choices if item[2]["median_validation_return"] >= best_return - 1e-12]
            best_score = max(row["score"] for _, _, row in choices)
            eligible = [(pair, name, row) for pair, name, row in choices
                        if row["score"] >= best_score - config.simplicity_tolerance]
            # Stable near-ties prefer simple allocation, consistent fold results,
            # fewer trades, less turnover/regret, then proximity to the seed.
            pair, name, _ = min(eligible, key=lambda item: (
                POLICY_ORDER.index(item[1]), pstdev(item[2]["fold_scores"]),
                item[2]["median_trade_count"], item[2]["median_turnover"],
                item[2]["median_validation_regret"],
                abs(item[0][0] - self.original[0]) + abs(item[0][1] - self.original[1]), item[0]))
            selected = (pair, name)
            if pair == center:
                break
            center = pair
        self.selected_pair, self.selected = selected
        self.study = self.cache[self.selected_pair][0][-1]
        self.study.selected = self.selected
        self.baseline = self.cache[self.original][0][-1]
        # Threshold stability describes independent fold winners over the same
        # evaluated development candidates; it is not fitted from test returns.
        winners = []
        for index in range(len(self.folds)):
            eligible_pairs = [pair for pair, (_, rows) in self.cache.items()
                              if any(not row["risk_rejected"] for row in rows.values())]
            if eligible_pairs:
                winners.append(max(eligible_pairs, key=lambda pair: max(
                    row["fold_scores"][index] for row in self.cache[pair][1].values() if not row["risk_rejected"])))
        self.stability = dict(fold_winners=[dict(buy=p[0], sell=p[1]) for p in winners],
                              buy_std=pstdev(p[0] for p in winners) if winners else 0.,
                              sell_std=pstdev(p[1] for p in winners) if winners else 0., available=bool(winners))

    def report(self, test):
        if self._reported:
            raise ValueError("final test has already been evaluated")
        if not self.folds[-1][1][1] < test[0] <= test[1] < len(self.base["close"]):
            raise ValueError("final test must follow validation")
        self._reported = True
        report = self.study.report(test)
        # Original thresholds/current allocation versus tuned-threshold policies.
        current = next(row for row in report["policies"] if row["name"] == "CURRENT")
        if self.selected_pair == self.original:
            original = dict(current)
        else:
            run = self.baseline.simulate(self.baseline.policies["CURRENT"], test, "TEST")
            original = dict(name="CURRENT", metrics={
                "train": allocation_metrics(self.baseline.training_runs["CURRENT"], self.baseline.train),
                "validation": allocation_metrics(self.baseline.validation_runs["CURRENT"], self.baseline.validation),
                "test": allocation_metrics(run, test)}, transitions=run["transitions"], executions=run["executions"],
                score_observations=run["score_observations"], trigger_signature=run["trigger_signature"],
                economic_curve=run["economic_curve"],
                test_equity=dict(dates=self.base["dates"][test[0]:test[1] + 1],
                                 values=[(v - 1) * 100 for v in run["equity"]]))
        current["name"] = "THRESHOLD_CURRENT"
        report["policies"].insert(1, original)
        report["selected_policy"] = "THRESHOLD_CURRENT" if self.selected == "CURRENT" else self.selected
        report["selection_basis"] = "walk_forward_joint_threshold_allocation"
        report["selection_status"] = "SELECTED" if self.selected is not None else "NO_RISK_ELIGIBLE_CANDIDATE"
        selected_row = next((row for row in report["policies"] if row["name"] == report["selected_policy"]), None)
        report["test_risk_status"] = ("BREACH" if selected_row["metrics"]["test"]["risk_rejected"] else "PASSED") if selected_row else "NOT_SELECTED"
        report["benchmark_status"] = self.study.validation_runs["CURRENT"]["economic_summary"]["benchmark_status"]
        report["joint_thresholds"] = dict(
            original=dict(buy=self.original[0], sell=self.original[1]),
            selected=dict(buy=self.selected_pair[0], sell=self.selected_pair[1]),
            iterations=self.iterations, candidates_evaluated=len(self.cache), threshold_stability=self.stability,
            folds=[dict(train=list(tr), validation=list(va),
                        train_dates=[self.base["dates"][tr[0]], self.base["dates"][tr[1]]],
                        validation_dates=[self.base["dates"][va[0]], self.base["dates"][va[1]]]) for tr, va in self.folds],
            candidates=[dict(buy=pair[0], sell=pair[1], policies=rows) for pair, (_, rows) in self.cache.items()],
            validation_metrics_basis="last_fold; full walk-forward metrics in candidates",
            selected_validation=self.cache[self.selected_pair][1].get(self.selected))
        return report
