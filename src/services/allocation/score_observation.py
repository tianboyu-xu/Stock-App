"""Finalized-bar diagnostics. Forward outcomes never enter policy/state inputs."""

from dataclasses import asdict, dataclass


@dataclass
class ScoreObservation:
    date: str
    buy_score: float
    sell_score: float
    buy_threshold: float
    sell_threshold: float
    triggered: bool
    exposure: float
    cash: float
    asset_forward_return: float = 0.0
    missed_buy_regret: float = 0.0
    missed_sell_regret: float = 0.0
    opportunity_reason: str = "NO_REGRET"
    horizon: str = "NEXT_OPEN_TO_CLOSE"

    def evaluate(self, forward_return, band):
        self.asset_forward_return = forward_return
        if self.triggered or band <= 0:
            return self
        buy_distance = self.buy_threshold - self.buy_score
        sell_distance = self.sell_score - self.sell_threshold
        # Strictly below the trigger, within a bounded band. Non-overlapping
        # one-bar outcomes avoid counting a future rally repeatedly to next trigger.
        if 0 < buy_distance < band:
            self.missed_buy_regret = (1 - buy_distance / band) * max(0., forward_return) * self.cash
        if 0 < sell_distance < band:
            self.missed_sell_regret = (1 - sell_distance / band) * max(0., -forward_return) * self.exposure
        if self.missed_buy_regret or self.missed_sell_regret:
            self.opportunity_reason = "THRESHOLD_MISSED_TRIGGER"
        return self

    def to_dict(self):
        return asdict(self)
