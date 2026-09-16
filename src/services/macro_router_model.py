"""Quarter-grouped, nested expanding-window selection for the MATR router.

Inputs are one point-in-time macro snapshot and one causal utility per family
per completed quarter. Window count never inflates the macro sample count.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class RouterSettings:
    min_train_quarters: int = 12
    inner_min_quarters: int = 8
    inner_validation_quarters: int = 4
    max_features: int = 6
    min_sign_stability: float = .75
    min_correlation: float = .15
    confidence_error_fraction: float = .10


DEFAULT_SETTINGS = RouterSettings()
# A small, declared search; every choice is selected inside the training prefix.
MODEL_CANDIDATES = (
    {"ridge": 1., "analog_k": 3, "predictive_weight": .7},
    {"ridge": 1., "analog_k": 5, "predictive_weight": .4},
    {"ridge": 10., "analog_k": 3, "predictive_weight": .7},
    {"ridge": 10., "analog_k": 5, "predictive_weight": .4},
)


def _rank(values):
    """Average ranks for ties, without adding scipy/sklearn dependencies."""
    values = np.asarray(values, dtype=float)
    _, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
    ranks = np.cumsum(counts) - (counts - 1) / 2
    return ranks[inverse]


def _correlation(x, y):
    x, y = _rank(x), _rank(y)
    if np.std(x) < 1e-12 or np.std(y) < 1e-12:
        return 0.
    return float(np.corrcoef(x, y)[0, 1])


def correlation_evidence(rows, families, settings=DEFAULT_SETTINGS):
    """Spearman against relative utility; stability uses expanding prefixes."""
    features = sorted(set.intersection(*(set(row["features"]) for row in rows)))
    targets = np.array([[row["utilities"][key] for key in families] for row in rows])
    relative = targets - targets.mean(axis=1, keepdims=True)
    evidence = []
    for feature in features:
        values = np.array([row["features"][feature] for row in rows], dtype=float)
        if not np.isfinite(values).all() or np.std(values) < 1e-12:
            continue
        for j, family in enumerate(families):
            corr = _correlation(values, relative[:, j])
            ends = sorted(set([max(4, len(rows) // 2), max(4, 3 * len(rows) // 4), len(rows)]))
            prefix = [_correlation(values[:end], relative[:end, j]) for end in ends]
            stability = sum(value * corr > 0 for value in prefix) / len(prefix)
            evidence.append(dict(feature=feature, strategy_key=family,
                                 correlation=round(corr, 6), sign_stability=stability,
                                 sample_count=len(rows), recent_correlation=round(
                                     _correlation(values[-max(4, len(rows) // 2):],
                                                  relative[-max(4, len(rows) // 2):, j]), 6)))
    strength = {}
    for item in evidence:
        if (item["sign_stability"] >= settings.min_sign_stability
                and abs(item["correlation"]) >= settings.min_correlation):
            strength[item["feature"]] = max(strength.get(item["feature"], 0.),
                                            abs(item["correlation"]) * item["sign_stability"])
    selected = sorted(strength, key=lambda key: (-strength[key], key))[:settings.max_features]
    return selected, evidence


def _fit_predict(rows, target, families, candidate, settings):
    features, evidence = correlation_evidence(rows, families, settings)
    y = np.array([[row["utilities"][key] for key in families] for row in rows])
    center = y.mean(axis=0)
    missing = [key for key in features if key not in target["features"]]
    if not features or missing:
        return dict(scores=np.zeros(len(families)), analog=np.zeros(len(families)),
                    features=features, evidence=evidence, analog_quarters=[],
                    usable=False, reason="missing_selected_features" if missing else "no_stable_features")
    x = np.array([[row["features"][key] for key in features] for row in rows], dtype=float)
    current = np.array([target["features"][key] for key in features], dtype=float)
    if not np.isfinite(current).all():
        raise ValueError("Macro features must be finite")
    # The held-out quarter never contributes to scaling, feature selection or fit.
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale = np.where(scale < 1e-12, 1., scale)
    z, query = (x - mean) / scale, (current - mean) / scale
    coefficients = np.linalg.solve(z.T @ z + candidate["ridge"] * np.eye(len(features)),
                                   z.T @ (y - center))
    prediction = center + query @ coefficients
    nearest = np.argsort(np.sum((z - query) ** 2, axis=1), kind="stable")[:candidate["analog_k"]]
    analog = y[nearest].mean(axis=0)
    weight = candidate["predictive_weight"]
    return dict(scores=weight * prediction + (1 - weight) * analog, analog=analog,
                features=features, evidence=evidence, usable=True,
                analog_quarters=[rows[i]["quarter"] for i in nearest],
                normalized_features={key: float(value) for key, value in zip(features, query)})


def _selection_policy(fit, families, prediction_error, settings):
    """Abstain on advantage over cash, independently of family ranking ambiguity.

    Two profitable families can be near substitutes. Their mutual score gap
    measures confidence in the family choice, not whether to remain in cash.
    Adding an identical candidate must not turn an eligible investment to cash.
    """
    ranking = [dict(strategy_key=key, expected_utility=float(score), analog_utility=float(analog))
               for key, score, analog in zip(families, fit["scores"], fit["analog"])]
    ranking.append(dict(strategy_key="CASH", expected_utility=0., analog_utility=0.))
    # Prefer cash at a zero tie, then the simpler existing family on exact ties.
    ranking.sort(key=lambda item: (-item["expected_utility"], item["strategy_key"] != "CASH",
                                   item["strategy_key"]))
    gap = ranking[0]["expected_utility"] - ranking[1]["expected_utility"]
    eligible = (fit["usable"] and prediction_error is not None
                and ranking[0]["expected_utility"] > settings.confidence_error_fraction * prediction_error)
    chosen = ranking[0]["strategy_key"] if eligible else "CASH"
    return chosen, ranking, gap, eligible


def select_strategy(rows: list[dict[str, Any]], target: dict[str, Any],
                    families: list[str], settings=DEFAULT_SETTINGS):
    """Predict using only fully completed quarters strictly before target.

Returns CASH for insufficient/stable-feature evidence or expected advantage
over cash smaller than a fraction of the inner-fold prediction error.
"""
    rows = sorted((row for row in rows if row["quarter"] < target["quarter"]),
                  key=lambda row: row["quarter"])
    if len({row["quarter"] for row in rows}) != len(rows):
        raise ValueError("MATR requires one independent row per quarter")
    if "CASH" in families or len(set(families)) != len(families) or not families:
        raise ValueError("Candidate families must be unique technical strategies")
    for row in rows:
        if not all(np.isfinite(row["utilities"][key]) for key in families):
            raise ValueError("Quarter utility must be finite")
    base = dict(selected_strategy="CASH", confidence="low", score_gap=0.,
                training_quarters=len(rows), training_through=rows[-1]["quarter"] if rows else None,
                ranking=[], top_features=[], correlations=[], analog_quarters=[],
                model_settings=asdict(settings))
    if len(rows) < settings.min_train_quarters:
        return {**base, "reason": "insufficient_completed_quarters", "available": False}
    inner_start = max(settings.inner_min_quarters, len(rows) - settings.inner_validation_quarters)
    if inner_start < 4 or inner_start >= len(rows):
        raise ValueError("MATR inner validation requires a training prefix and held-out quarters")
    # A bounded preceding block initializes uncertainty before the first scored
    # inner fold. It never uses that fold's utility or any later quarter's label.
    calibration_start = max(4, inner_start - settings.inner_validation_quarters)
    candidates = []
    for candidate in MODEL_CANDIDATES:
        utilities, errors, folds = [], [], []
        for index in range(calibration_start, len(rows)):
            fit = _fit_predict(rows[:index], rows[index], families, candidate, settings)
            scores = fit["scores"]
            # Select before adding this fold's errors to the expanding estimate.
            prior_error = float(np.sqrt(np.mean(np.square(errors)))) if errors else None
            chosen, ranking, gap, _ = _selection_policy(fit, families, prior_error, settings)
            if index >= inner_start:
                realized = rows[index]["utilities"].get(chosen, 0.)
                utilities.append(realized)
                folds.append(dict(quarter=rows[index]["quarter"],
                                  trained_through=rows[index - 1]["quarter"],
                                  selected_strategy=chosen, utility=realized, score_gap=gap,
                                  cash_margin=max(item["expected_utility"] for item in ranking
                                                  if item["strategy_key"] != "CASH"),
                                  prediction_error=prior_error,
                                  confidence_threshold=(settings.confidence_error_fraction * prior_error
                                                        if prior_error is not None else None)))
            actual = np.array([rows[index]["utilities"][key] for key in families])
            errors.extend((actual - scores).tolist())
        objective = float(np.mean(utilities) - np.std(utilities))
        candidates.append(dict(parameters=candidate, objective=objective, folds=folds,
                               calibration_quarters=[row["quarter"] for row in rows[calibration_start:inner_start]],
                               prediction_rmse=float(np.sqrt(np.mean(np.square(errors))))))
    best_model = max(candidates, key=lambda item: item["objective"])
    fit = _fit_predict(rows, target, families, best_model["parameters"], settings)
    error = best_model["prediction_rmse"]
    chosen, ranking, gap, eligible = _selection_policy(fit, families, error, settings)
    threshold = settings.confidence_error_fraction * error
    return {**base, "available": True, "selected_strategy": chosen, "ranking": ranking,
            "confidence": ("high" if eligible and gap > error else
                           "medium" if eligible and gap > threshold else "low"),
            "cash_margin": max(item["expected_utility"] for item in ranking
                               if item["strategy_key"] != "CASH"),
            "confidence_threshold": threshold,
            "score_gap": gap, "prediction_error": error, "top_features": fit["features"],
            "correlations": fit["evidence"], "analog_quarters": fit["analog_quarters"],
            "normalized_features": fit.get("normalized_features", {}),
            "model_parameters": best_model["parameters"], "inner_validation": candidates,
            "reason": fit.get("reason", "cash_preferred" if ranking[0]["strategy_key"] == "CASH" else
                              "low_expected_advantage" if not eligible else "positive_expected_utility")}
