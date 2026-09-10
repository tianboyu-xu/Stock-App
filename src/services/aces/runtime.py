"""Causal ACES state, risk and execution adapters for the shared simulator."""

from bisect import bisect_right
from dataclasses import dataclass, replace
from datetime import date
import math

from src.services.allocation.allocation_state import AllocationState, StateEncoder


@dataclass(frozen=True)
class ACESState(AllocationState):
    volatility_regime: str = "NORMAL"
    drawdown_bucket: str = "0_5"


class ACESStateEncoder(StateEncoder):
    def __init__(self, config, base):
        super().__init__(replace(config.allocation.state, use_regime=True))
        self.base, self.risk = base, config.risk

    def encode(self, trigger, portfolio):
        state = super().encode(trigger, portfolio)
        index = trigger.index
        stress = bisect_right(self.risk.drawdown_edges, round(max(0., -portfolio.drawdown), 12))
        boundaries = (0., *self.risk.drawdown_edges)
        label = (f"{boundaries[stress] * 100:g}_{boundaries[stress + 1] * 100:g}"
                 if stress < len(self.risk.drawdown_edges) else f"{boundaries[-1] * 100:g}_PLUS")
        return ACESState(**state.to_dict(), volatility_regime=self.base["volatility_regime"][index],
                         drawdown_bucket=label)


def prepare_context(base, config):
    """Reuse cached SMA/ATR. Classify the same price-and-slope trend as score_bar.

    ATR percentile references strictly earlier finalized bars. No indicator is
    recomputed here; unavailable lookbacks block new exposure until warmup ends.
    """
    result = dict(base)
    ratios, regimes, volatilities = [], [], []
    for i, close in enumerate(base["close"]):
        atr = base["atr"][i]
        ratio = atr / close if atr is not None and atr > 0 else None
        past = sorted(x for x in ratios[max(0, i - config.risk.volatility_lookback):i] if x is not None)
        rank = sum(x <= ratio for x in past) / len(past) if ratio is not None and len(past) >= 20 else None
        volatilities.append(("LOW", "NORMAL", "HIGH", "EXTREME")[bisect_right(
            config.risk.volatility_percentiles, rank)] if rank is not None else "UNKNOWN")
        ratios.append(ratio)
        sma = base["sma200"][i]
        previous = base["sma200"][i - 1] if i else None
        regimes.append("UNKNOWN" if sma is None or previous is None else
                       "BULL" if close > sma > previous else "BEAR" if close < sma < previous else "SIDEWAYS")
    result.update(regime=regimes, volatility_regime=volatilities, normalized_atr=ratios)
    return result


class RiskEngine:
    def __init__(self, config, base):
        self.config, self.base = config, base

    def cap(self, snapshot, index):
        risk = self.config.risk
        if snapshot.cash < -1e-12 or snapshot.shares < 0 or snapshot.nav <= 0:
            raise ValueError("SYSTEM_SAFE_MODE: invalid portfolio")
        if -snapshot.drawdown > self.config.allocation.economic.allowed_max_drawdown:
            return 0., "DRAWDOWN_LIMIT"
        regime = self.base["volatility_regime"][index]
        if self.base["regime"][index] == "UNKNOWN" or regime == "UNKNOWN":
            return 0., "FEATURE_WARMUP"
        volatility_cap = risk.volatility_caps[("LOW", "NORMAL", "HIGH", "EXTREME").index(regime)] if risk.volatility_control else 1.
        return min(risk.maximum_exposure, volatility_cap), (
            "VOLATILITY_CAP" if volatility_cap < risk.maximum_exposure else "MAXIMUM_EXPOSURE")

    def allow(self, desired, snapshot, index):
        cap, reason = self.cap(snapshot, index)
        target = snapshot.current_exposure if desired is None else desired
        return (min(target, cap) if target > cap + 1e-12 else desired), (reason if target > cap + 1e-12 else "ALLOWED")


class ACESRuntime:
    """Stateless adapter: every replay gets the same cash, cost and risk rules.

    A risk reduction is a protective order and may override BUY direction or
    spacing. Caps are rechecked at each executable open using prior-close data.
    Price drift between fills can exceed a target cap; it is recorded, not hidden.
    """
    def __init__(self, config, base):
        self.config, self.base = config, base
        self.risk = RiskEngine(config, base)

    def cost(self, index):
        c = self.config.execution
        ratio = self.base["normalized_atr"][index] or 0.
        volume = self.base["volume"][index]
        average = self.base["vol_sma20"][index]
        illiquidity = max(0., average / max(volume, 1.) - 1) if average else 0.
        cost = (c.cost_pct_per_side / 100 + c.volatility_slippage_factor * ratio
                + c.liquidity_slippage_factor * illiquidity)
        if not math.isfinite(cost) or not 0 <= cost < 1:
            raise ValueError("SYSTEM_SAFE_MODE: effective cost outside [0,1)")
        return cost

    def price(self, target, snapshot, price):
        c = self.config.execution
        if target > snapshot.current_exposure + 1e-12:
            return price * (1 + c.entry_worsening)
        if target < snapshot.current_exposure - 1e-12:
            return price * (1 - c.exit_worsening)
        return price

    def accrue(self, env, index, start):
        if index > start:
            days = (date.fromisoformat(self.base["dates"][index])
                    - date.fromisoformat(self.base["dates"][index - 1])).days
            env.accrue_cash(self.config.execution.cash_yield, days)

    def metadata(self, index):
        return dict(market_regime=self.base["regime"][index],
                    volatility_regime=self.base["volatility_regime"][index],
                    volatility=self.base["normalized_atr"][index], atr=self.base["atr"][index],
                    close=self.base["close"][index], signal_status="CONFIRMED",
                    next_execution_reference="NEXT_REGULAR_SESSION_OPEN")


def validate_bars(bars, *, last_confirmed_date):
    """Caller provides the last completed session; live previews never trade.

    The historical API conservatively excludes today's bar. A live session
    scheduler must explicitly provide its confirmed session date.
    """
    previous = None
    if not bars:
        raise ValueError("SYSTEM_SAFE_MODE: missing bars")
    for bar in bars:
        day = date.fromisoformat(bar["date"])
        if previous is not None and day <= previous:
            raise ValueError("SYSTEM_SAFE_MODE: duplicate or unordered dates")
        if day > last_confirmed_date or bar.get("finalized") is False:
            raise ValueError("SYSTEM_SAFE_MODE: PREVIEW bar is not confirmed")
        values = [bar[key] for key in ("open", "high", "low", "close")]
        if any(not math.isfinite(x) or x <= 0 for x in values) or not (
            bar["low"] <= min(bar["open"], bar["close"]) <= max(bar["open"], bar["close"]) <= bar["high"]
        ):
            raise ValueError("SYSTEM_SAFE_MODE: invalid OHLC")
        volume = bar.get("volume", 0.)
        if not math.isfinite(volume) or volume < 0:
            raise ValueError("SYSTEM_SAFE_MODE: invalid volume")
        previous = day
