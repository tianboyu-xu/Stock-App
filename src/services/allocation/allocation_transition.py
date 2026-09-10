"""Inspectable trigger-to-trigger portfolio transitions."""

from dataclasses import asdict, dataclass
from datetime import date
import math

from .allocation_state import AllocationState
from .portfolio_environment import PortfolioSnapshot, Rebalance


def log_nav_reward(nav_current: float, nav_next: float) -> float:
    if not all(math.isfinite(v) and v > 0 for v in (nav_current, nav_next)):
        raise ValueError("reward requires positive finite NAV")
    return math.log(nav_next / nav_current)


@dataclass
class AllocationTransition:
    trigger_date: str
    trigger_direction: str
    trigger_score: float
    state_before: AllocationState
    portfolio_before: PortfolioSnapshot
    requested_target_exposure: float | None
    policy_reason: str
    execution_date: str | None = None
    execution: Rebalance | None = None
    execution_reason: str = "NO_NEXT_BAR"
    next_trigger_date: str | None = None
    next_price: float | None = None
    nav_at_next_trigger: float | None = None
    reward: float = 0.0
    state_after: AllocationState | None = None
    duration_days: int = 0
    market_move: float = 0.0
    q_value: float | None = None
    visit_count: int = 0
    terminal: bool = False
    portfolio_reward: float = 0.0
    reward_before_regret: float = 0.0
    reward_after_regret: float = 0.0
    opportunity_regret: float = 0.0
    counterfactual_regret: float = 0.0
    missed_upside_regret: float = 0.0
    missed_downside_regret: float = 0.0
    foregone_exposure: float = 0.0
    foregone_reduction: float = 0.0
    foregone_upside_regret: float = 0.0
    foregone_downside_regret: float = 0.0
    asset_forward_return: float = 0.0
    opportunity_reason: str = "NO_REGRET"
    best_feasible_action: float | None = None
    best_feasible_return: float = 0.0
    action_returns: list | None = None
    threshold: float | None = None
    distance_from_threshold: float | None = None
    economic: dict | None = None
    allowed_target_exposure: float | None = None
    risk_reason: str = "NOT_APPLICABLE"
    signal_status: str = "CONFIRMED"
    q_confidence: str = "UNSEEN"

    def finish(self, next_date, portfolio, next_state=None, terminal=False):
        self.next_trigger_date = next_date
        self.next_price = portfolio.last_price
        self.nav_at_next_trigger = portfolio.nav
        self.reward = log_nav_reward(self.portfolio_before.nav, portfolio.nav)
        self.portfolio_reward = self.reward_before_regret = self.reward_after_regret = self.reward
        self.state_after = next_state
        self.terminal = terminal
        self.duration_days = (date.fromisoformat(next_date) - date.fromisoformat(self.trigger_date)).days
        self.market_move = portfolio.last_price / self.portfolio_before.last_price - 1

    def to_dict(self):
        result = asdict(self)
        after = self.execution.after if self.execution else self.portfolio_before
        result.update(cash_before=self.portfolio_before.cash, cash_after=after.cash,
                      desired_target_exposure=self.requested_target_exposure,
                      actual_target_exposure=after.current_exposure, score=self.trigger_score)
        if self.execution:
            result["trade_nav_fraction"] = self.execution.trade_value / self.execution.before.nav
            result["cash_spent_fraction"] = ((self.execution.trade_value + self.execution.transaction_cost)
                                             / self.execution.before.cash if self.execution.side == "BUY"
                                             and self.execution.before.cash > 0 else None)
        result.update(self.economic or {})
        return result
