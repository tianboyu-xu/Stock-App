"""Bounded discrete coordinate search; the evaluator must contain training data only."""

from .allocation_state import TARGET_EXPOSURES
from .fixed_score_policy import FixedScorePolicy


def mapping_candidates(policy):
    for index in range(6):
        for value in TARGET_EXPOSURES:
            values = list(policy.targets)
            values[index] = value
            if values[0] >= values[1] >= values[2] and values[3] >= values[4] >= values[5]:
                yield FixedScorePolicy(*values, name="TUNED_FIXED")


def tune_fixed(evaluate_train, sweeps=2):
    """Maximize after-cost training log NAV; exact ties keep the simpler incumbent.

    Two sweeps bound runtime instead of exhaustively testing all 3,136 mappings.
    No validation/test arrays or metrics are accepted by this interface.
    """
    best = FixedScorePolicy(name="TUNED_FIXED")
    score = evaluate_train(best)
    cache = {best.targets: score}
    for _ in range(sweeps):
        incumbent = best
        for candidate in mapping_candidates(incumbent):
            if candidate.targets not in cache:
                cache[candidate.targets] = evaluate_train(candidate)
            if cache[candidate.targets] > score + 1e-12:
                best, score = candidate, cache[candidate.targets]
        if best == incumbent:
            break
    return best, len(cache)
