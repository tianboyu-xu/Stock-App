"""Direction-preserving target actions and explainable policy decisions."""

from dataclasses import dataclass
from typing import Protocol

from .allocation_state import TARGET_EXPOSURES


def get_valid_actions(portfolio, trigger):
    """None is an explicit no-op, including when actual exposure is off-grid."""
    exposure = portfolio.current_exposure
    if trigger.direction == "BUY":
        targets = tuple(x for x in TARGET_EXPOSURES if x >= exposure - 1e-12)
    elif trigger.direction == "SELL":
        targets = tuple(x for x in TARGET_EXPOSURES if x <= exposure + 1e-12)
    else:
        targets = ()
    return (*targets, None)


@dataclass(frozen=True)
class PolicyDecision:
    target: float | None
    reason: str
    q_value: float | None = None
    visit_count: int = 0


class AllocationPolicy(Protocol):
    name: str

    def choose(self, state, trigger, portfolio) -> PolicyDecision: ...
