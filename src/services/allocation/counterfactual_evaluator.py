"""Outcome-only feasible alternatives, including the same costs and protective exits."""

from dataclasses import dataclass, replace
import math

from .portfolio_environment import PortfolioEnvironment
from .position_protection import PositionProtection


def foregone_regret(direction, desired, actual, asset_return, cash_return=0.0):
    """Requested-exposure shortfall diagnostics, separate from feasible-action regret."""
    buy = max(0., desired - actual) if direction == "BUY" else 0.
    sell = max(0., actual - desired) if direction == "SELL" else 0.
    excess = asset_return - cash_return
    return dict(foregone_exposure=buy, foregone_reduction=sell,
                foregone_upside_regret=buy * max(0., excess),
                foregone_downside_regret=sell * max(0., -excess))


@dataclass(frozen=True)
class CounterfactualResult:
    actual_action: float | None
    actual_return: float
    best_feasible_action: float | None
    best_feasible_return: float
    regret: float
    action_returns: list


class CounterfactualEvaluator:
    def evaluate(self, snapshot, valid_actions, actual_action, next_price, *,
                 transaction_cost=0.0, execution_price=None, base=None, start=None, end=None,
                 protection=None, stop_multiple_atr=None, trail_multiple_atr=None, terminal=False, runtime=None):
        """Replay one decision interval. Caller supplies time-t execution-feasible actions.

        Returns use a common pre-execution NAV denominator and logarithmic units.
        No borrowing/shorting is possible; the shared environment solves fees. When
        a path is supplied, stops/trails and terminal liquidation match simulation.
        Future prices are used here only after the actual transition has finished.
        """
        actions = tuple(dict.fromkeys(valid_actions))
        if actual_action not in actions:
            raise ValueError("actual action must be feasible")
        if any(a is not None and (not math.isfinite(a) or not 0 <= a <= 1) for a in actions):
            raise ValueError("infeasible target exposure")
        rows = []
        for action in actions:
            env = PortfolioEnvironment.from_snapshot(snapshot, transaction_cost)
            guard = replace(protection) if protection else PositionProtection()
            price = execution_price if execution_price is not None else snapshot.last_price
            at_open = env.mark_to_market(price)
            target = at_open.current_exposure if action is None else action
            if runtime:
                price = runtime.price(target, at_open, price)
            result = env.rebalance(target, price)
            atr = base["atr"][start - 1] if base is not None and start > 0 else None
            if result.side != "HOLD":
                guard.after_fill(result, atr, stop_multiple_atr)
            if base is not None:
                if start is None or end is None or not 0 <= start <= end < len(base["close"]):
                    raise ValueError("invalid counterfactual path")
                for i in range(start, end + 1):
                    if runtime:
                        runtime.accrue(env, i, start)
                        env.transaction_cost = runtime.cost(max(start - 1, i - 1))
                        current = env.mark_to_market(base["open"][i])
                        cap, _ = runtime.risk.cap(current, i - 1)
                        if current.current_exposure > cap + 1e-12:
                            fill = env.rebalance(cap, runtime.price(cap, current, base["open"][i]))
                            guard.after_fill(fill, base["atr"][i - 1], stop_multiple_atr)
                    level, _ = guard.exit_level()
                    if env.shares and level is not None and base["low"][i] <= level:
                        price = min(base["open"][i], level)
                        if runtime:
                            price = runtime.price(0, env.mark_to_market(price), price)
                        fill = env.rebalance(0, price)
                        guard.after_fill(fill, None, stop_multiple_atr)
                    env.mark_to_market(base["close"][i])
                    if env.shares:
                        guard.close(base["close"][i], trail_multiple_atr)
            env.mark_to_market(next_price)
            if terminal and env.shares:
                env.rebalance(0, runtime.price(0, env.snapshot, next_price) if runtime else next_price)
            rows.append(dict(action=action, next_nav=env.snapshot.nav,
                             log_return=math.log(env.snapshot.nav / snapshot.nav)))
        actual = next(row for row in rows if row["action"] == actual_action)
        best = max(rows, key=lambda row: row["log_return"])
        # Prefer actual on exact ties, avoiding invented missed-opportunity labels.
        if best["log_return"] - actual["log_return"] <= 1e-12:
            best = actual
        return CounterfactualResult(actual_action, actual["log_return"], best["action"],
                                    best["log_return"], max(0., best["log_return"] - actual["log_return"]), rows)
