"""Transparent fixed target mapping, also used as Q-learning's fallback."""

from dataclasses import dataclass

from .allocation_policy import PolicyDecision, get_valid_actions
from .allocation_state import TARGET_EXPOSURES


@dataclass(frozen=True)
class FixedScorePolicy:
    strong_buy_target: float = 1.0
    medium_buy_target: float = .8
    weak_buy_target: float = .6
    weak_sell_target: float = .4
    medium_sell_target: float = .2
    strong_sell_target: float = 0.0
    name: str = "FIXED"

    def __post_init__(self):
        values = self.targets
        if any(x not in TARGET_EXPOSURES for x in values):
            raise ValueError("fixed targets must be members of the exposure grid")
        if not values[0] >= values[1] >= values[2] or not values[3] >= values[4] >= values[5]:
            raise ValueError("fixed targets must be monotonic within each direction")

    @property
    def targets(self):
        return (self.strong_buy_target, self.medium_buy_target, self.weak_buy_target,
                self.weak_sell_target, self.medium_sell_target, self.strong_sell_target)

    def choose(self, state, trigger, portfolio):
        mapping = dict(zip(("STRONG_BUY", "MEDIUM_BUY", "WEAK_BUY", "WEAK_SELL", "MEDIUM_SELL", "STRONG_SELL"),
                           self.targets))
        target = mapping.get(state.trigger_bucket)
        if target not in get_valid_actions(portfolio, trigger):
            return PolicyDecision(None, "DIRECTION_MASK_HOLD")
        return PolicyDecision(target, "FIXED_MAPPING" if target is not None else "NEUTRAL_HOLD")


class CurrentAllocationPolicy:
    """Previous single-position score/cash-budget entry, converted to target exposure."""
    name = "CURRENT"

    def __init__(self, allocations, cost):
        self.allocations = allocations
        self.cost = cost

    def choose(self, state, trigger, portfolio):
        if trigger.direction == "BUY":
            if portfolio.shares:
                return PolicyDecision(None, "POSITION_OPEN")
            # Budget-to-target conversion belongs to the portfolio environment.
            from .portfolio_environment import PortfolioEnvironment
            env = PortfolioEnvironment(self.cost, portfolio.nav)
            target = env.target_for_budget_fraction(self.allocations[trigger.index])
            return PolicyDecision(target, "CURRENT_SCORE_BUDGET")
        return PolicyDecision(0.0 if trigger.direction == "SELL" else None, "CURRENT_EXIT")
