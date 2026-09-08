"""Descriptive uncertainty for a frozen strategy's final test equity.

Circular blocks preserve local return dependence and sample both ends equally.
See https://bashtage.github.io/arch/bootstrap/timeseries-bootstraps.html.
This is conditional on the observed path; it does not correct multiple testing,
estimate a probability of future profit, or feed parameter selection.
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, Optional, Sequence

from src.services.strategy_backtester import TRADING_DAYS_PER_YEAR


def _sharpe(returns: Sequence[float]) -> Optional[float]:
    # Scaling preserves Sharpe while avoiding overflow in squared deviations.
    scale = max(1.0, max(abs(value) for value in returns))
    scaled = [value / scale for value in returns]
    mean = sum(scaled) / len(scaled)
    variance = sum((value - mean) ** 2 for value in scaled) / len(scaled)
    if variance <= 1e-20:
        return None
    return mean / math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR)


def _percentile(values: Sequence[float], fraction: float) -> float:
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def summarize_test_confidence(
    simulation: Dict[str, Any], seed: int = 0,
) -> Dict[str, Any]:
    """Return a reproducible 95% percentile interval, or an explicit limitation.

    The block length ceil(n ** (1/3)) is a disclosed heuristic, not a tuned
    parameter. Zero-variance resamples are excluded and their count is exposed.
    Daily returns include opening costs and final liquidation, as in metrics.
    """
    equity = simulation.get("equity") or []
    count = len(equity)
    block_length = max(1, math.ceil(count ** (1.0 / 3.0)))
    result: Dict[str, Any] = {
        "available": False,
        "method": "circular_block_bootstrap",
        "confidence_level": 0.95,
        "bars": count,
        "block_length": block_length,
        "resamples": 400,
        "valid_resamples": 0,
        "sharpe_ci_lower": None,
        "sharpe_ci_upper": None,
        "positive_sharpe_fraction": None,
        "reason": "insufficient_history",
    }
    if count < 60:
        return result
    if len(simulation.get("trades") or []) < 3:
        result["reason"] = "insufficient_trades"
        return result
    previous = float(simulation.get("initial_equity", 1.0))
    returns = []
    for value in equity:
        if not math.isfinite(previous) or previous <= 0 or not math.isfinite(value) or value <= 0:
            result["reason"] = "invalid_equity"
            return result
        daily_return = value / previous - 1.0
        if not math.isfinite(daily_return):
            result["reason"] = "invalid_equity"
            return result
        returns.append(daily_return)
        previous = value
    if _sharpe(returns) is None:
        result["reason"] = "zero_variance"
        return result
    rng = random.Random(seed)
    sharpes = []
    for _ in range(result["resamples"]):
        sampled = []
        while len(sampled) < count:
            start = rng.randrange(count)
            sampled.extend(
                returns[(start + offset) % count]
                for offset in range(min(block_length, count - len(sampled)))
            )
        sharpe = _sharpe(sampled)
        if sharpe is not None:
            sharpes.append(sharpe)
    result["valid_resamples"] = len(sharpes)
    if len(sharpes) < result["resamples"] * 0.9:
        result["reason"] = "insufficient_variable_resamples"
        return result
    sharpes.sort()
    result.update({
        "available": True,
        "reason": None,
        "sharpe_ci_lower": round(_percentile(sharpes, 0.025), 4),
        "sharpe_ci_upper": round(_percentile(sharpes, 0.975), 4),
        "positive_sharpe_fraction": round(sum(value > 0 for value in sharpes) / len(sharpes), 4),
    })
    return result
