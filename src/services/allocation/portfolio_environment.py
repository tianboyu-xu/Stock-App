"""Single source of truth for cash, shares, cost basis and marked NAV."""

from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class PortfolioSnapshot:
    cash: float
    shares: float
    nav: float
    stock_value: float
    current_exposure: float
    average_cost: float
    unrealized_pnl_pct: float
    peak_nav: float
    drawdown: float
    last_price: float

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Rebalance:
    requested_target_exposure: float
    actual_target_exposure: float
    side: str
    trade_value: float  # signed stock notional; excludes fees
    transaction_cost: float
    realized_profit: float
    reason: str
    before: PortfolioSnapshot
    after: PortfolioSnapshot


class PortfolioEnvironment:
    """Fractional-share portfolio. Costs combine commission, spread and slippage.

    Solve for exposure *after* fees: buy notional = (target*NAV-stock)/(1+target*c),
    sell notional = (stock-target*NAV)/(1-target*c). This avoids fee-induced
    overshooting and repeated same-target trades. Targets outside [0, 1] are errors.
    """

    def __init__(self, transaction_cost: float, initial_nav: float = 1.0):
        if not math.isfinite(transaction_cost) or not 0 <= transaction_cost < 1:
            raise ValueError("transaction_cost must be finite and in [0, 1)")
        if not math.isfinite(initial_nav) or initial_nav <= 0:
            raise ValueError("initial_nav must be positive and finite")
        self.transaction_cost = transaction_cost
        self.initial_nav = initial_nav
        self.cash = initial_nav
        self.shares = 0.0
        self.average_cost = 0.0
        self.last_price = 1.0
        self.peak_nav = initial_nav
        self.total_transaction_cost = 0.0
        self.turnover = 0.0
        self.trade_count = 0

    @property
    def snapshot(self) -> PortfolioSnapshot:
        stock = self.shares * self.last_price
        nav = self.cash + stock
        return PortfolioSnapshot(
            self.cash, self.shares, nav, stock, stock / nav if nav else 0.0,
            self.average_cost,
            self.last_price / self.average_cost - 1 if self.shares and self.average_cost else 0.0,
            self.peak_nav, nav / self.peak_nav - 1, self.last_price,
        )

    @classmethod
    def from_snapshot(cls, snapshot, transaction_cost):
        """Independent counterfactual portfolio; never mutate the live environment."""
        env = cls(transaction_cost, snapshot.nav)
        for key in ("cash", "shares", "average_cost", "last_price", "peak_nav"):
            setattr(env, key, getattr(snapshot, key))
        return env

    def mark_to_market(self, price: float) -> PortfolioSnapshot:
        if not math.isfinite(price) or price <= 0:
            raise ValueError("price must be positive and finite")
        self.last_price = price
        self.peak_nav = max(self.peak_nav, self.cash + self.shares * price)
        return self.snapshot

    def target_for_budget_fraction(self, fraction: float) -> float:
        """Compatibility with the previous cash-budget entry rule (flat only)."""
        if not 0 <= fraction <= 1 or self.shares:
            raise ValueError("cash-budget entry requires a flat portfolio and fraction in [0, 1]")
        notional = self.cash * fraction / (1 + self.transaction_cost)
        return min(1.0, notional / (self.cash - notional * self.transaction_cost))

    def accrue_cash(self, annual_yield: float, elapsed_days: int):
        if not math.isfinite(annual_yield) or not 0 <= annual_yield <= 1 or elapsed_days < 0:
            raise ValueError("invalid cash yield or elapsed time")
        self.cash *= (1 + annual_yield) ** (elapsed_days / 365.25)
        return self.mark_to_market(self.last_price)

    def rebalance(self, target_exposure: float, execution_price: float) -> Rebalance:
        if not math.isfinite(target_exposure) or not 0 <= target_exposure <= 1:
            raise ValueError("target_exposure must be finite and in [0, 1]; leverage is unsupported")
        before = self.mark_to_market(execution_price)
        delta = target_exposure * before.nav - before.stock_value
        cost = self.transaction_cost
        reason = "TARGET_EXPOSURE"
        profit = fee = value = 0.0
        side = "HOLD"
        if abs(target_exposure - before.current_exposure) > 1e-12:
            if delta > 0:
                affordable = self.cash / (1 + cost)
                value = min(delta / (1 + target_exposure * cost), affordable)
                if delta > affordable + 1e-12:
                    reason = "BUDGET_CONSTRAINED"
                fee = value * cost
                shares = value / execution_price
                self.average_cost = (self.average_cost * self.shares + value + fee) / (self.shares + shares)
                self.shares += shares
                self.cash = max(0.0, self.cash - value - fee)
                side = "BUY"
            else:
                sold = min(-delta / (1 - target_exposure * cost), before.stock_value)
                shares = self.shares if target_exposure == 0 else sold / execution_price
                fee = sold * cost
                profit = sold - fee - shares * self.average_cost
                self.cash += sold - fee
                self.shares = max(0.0, self.shares - shares)
                if self.shares == 0:
                    self.average_cost = 0.0
                value = -sold
                side = "SELL"
            self.trade_count += 1
            self.total_transaction_cost += fee
            self.turnover += abs(value) / before.nav
        else:
            reason = "SAME_TARGET"
        return Rebalance(target_exposure, self.snapshot.current_exposure, side, value, fee,
                         profit, reason, before, self.snapshot)
