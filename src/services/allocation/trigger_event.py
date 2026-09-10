"""Technical trigger inputs; allocation never recalculates indicators."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class TriggerEvent:
    timestamp: str
    direction: str
    score: float
    execution_price: float
    signal_price: float
    index: int = 0
    regime: str = "UNKNOWN"
    atr: float | None = None

    def __post_init__(self):
        if self.direction not in {"BUY", "SELL", "NEUTRAL"}:
            raise ValueError("direction must be BUY, SELL or NEUTRAL")
        if not all(math.isfinite(v) for v in (self.score, self.execution_price, self.signal_price)):
            raise ValueError("trigger values must be finite")
        if min(self.execution_price, self.signal_price) <= 0:
            raise ValueError("trigger prices must be positive")

    @property
    def signed_score(self):
        return abs(self.score) if self.direction == "BUY" else -abs(self.score) if self.direction == "SELL" else 0.0


def events_from_signals(base, signals, start, end):
    """Preserve original trigger dates and direction, including the last unfillable bar.

    Scores are supplied by StrategyEngine. No future features or prices are used in
    state encoding. Last-bar triggers are retained for explicit NO_NEXT_BAR logging.
    Regime stays UNKNOWN unless the caller supplies a causal classification series.
    """
    events = []
    for i in range(start, end + 1):
        for direction, key in (("BUY", "buy"), ("SELL", "sell")):
            if signals[f"{key}_signal"][i] is None:
                continue
            scores = signals.get(f"{key}_score")
            events.append(TriggerEvent(
                timestamp=base["dates"][i], direction=direction,
                score=scores[i] if scores is not None else 0.0,
                # Policy input is causal. This legacy-named field is a decision
                # reference only; actual next-open price belongs to execution.
                execution_price=base["close"][i],
                signal_price=base["close"][i], index=i,
                atr=base["atr"][i],
                regime=base["regime"][i] if "regime" in base else "UNKNOWN",
            ))
    return events
