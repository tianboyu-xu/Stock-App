"""Small, deterministic and hashable MDP state; no ticker or future information."""

from dataclasses import asdict, dataclass
import math

TARGET_EXPOSURES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


@dataclass(frozen=True)
class StateConfig:
    medium_score: float = 4.0
    strong_score: float = 7.0
    pnl_edges: tuple = (-.15, -.05, .05, .15)
    use_regime: bool = False

    def __post_init__(self):
        if not 0 < self.medium_score < self.strong_score or not math.isfinite(self.strong_score):
            raise ValueError("score thresholds must be finite and 0 < medium < strong")
        if len(self.pnl_edges) != 4 or any(not math.isfinite(x) for x in self.pnl_edges):
            raise ValueError("pnl_edges must contain four finite boundaries")
        if any(a >= b for a, b in zip(self.pnl_edges, self.pnl_edges[1:])):
            raise ValueError("pnl_edges must be strictly increasing")


@dataclass(frozen=True)
class AllocationState:
    trigger_bucket: str
    exposure_bucket: float
    pnl_bucket: str
    regime: str
    cash_bucket: str = "70_100"

    def to_dict(self):
        return asdict(self)


class StateEncoder:
    def __init__(self, config: StateConfig = StateConfig()):
        self.config = config

    def encode(self, trigger, portfolio):
        score = trigger.signed_score
        magnitude = abs(score)
        strength = "STRONG" if magnitude >= self.config.strong_score else (
            "MEDIUM" if magnitude >= self.config.medium_score else "WEAK")
        bucket = f"{strength}_{trigger.direction}" if magnitude else "NEUTRAL"
        exposure = min(TARGET_EXPOSURES, key=lambda x: (round(abs(x - portfolio.current_exposure), 12), x))
        a, b, c, d = self.config.pnl_edges
        pnl = portfolio.unrealized_pnl_pct
        pnl_bucket = "LOSS_LARGE" if pnl < a else "LOSS" if pnl < b else (
            "FLAT" if pnl <= c else "PROFIT" if pnl <= d else "PROFIT_LARGE")
        regime = trigger.regime if self.config.use_regime else "UNKNOWN"
        if regime not in {"UNKNOWN", "BULL", "BEAR", "SIDEWAYS"}:
            raise ValueError("unsupported market regime")
        cash = round(portfolio.cash / portfolio.nav, 12)
        cash_bucket = ("0_10" if cash < .1 else "10_30" if cash < .3 else
                       "30_50" if cash < .5 else "50_70" if cash < .7 else "70_100")
        return AllocationState(bucket, exposure, pnl_bucket, regime, cash_bucket)
