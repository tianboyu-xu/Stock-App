"""Shared causal stop/trail mechanics for actual and counterfactual portfolios."""

from dataclasses import dataclass


@dataclass
class PositionProtection:
    stop: float | None = None
    trail: float | None = None
    entry_atr: float | None = None
    highest_close: float = 0.0

    def after_fill(self, result, atr, stop_multiple):
        if result.side == "BUY":
            if not result.before.shares:
                self.highest_close = 0.0
            self.entry_atr = atr
            if stop_multiple and atr:
                level = result.after.average_cost - stop_multiple * atr
                self.stop = max(self.stop, level) if self.stop is not None else level
        elif not result.after.shares:
            self.stop = self.trail = self.entry_atr = None

    def exit_level(self):
        if self.trail is not None and (self.stop is None or self.trail > self.stop):
            return self.trail, "trail"
        return self.stop, "stop"

    def close(self, price, trail_multiple):
        self.highest_close = max(self.highest_close, price)
        if trail_multiple and self.entry_atr:
            level = self.highest_close - trail_multiple * self.entry_atr
            self.trail = max(self.trail, level) if self.trail is not None else level
