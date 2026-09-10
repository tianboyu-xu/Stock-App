"""Versioned, request-scoped ACES settings. Fractions, not percentages."""

from dataclasses import asdict, dataclass, field
import math

from src.services.allocation.research import AllocationConfig
from src.services.allocation.economic_reward import EconomicConfig
from src.services.allocation.allocation_state import StateConfig

ACES_VERSION = 1


@dataclass(frozen=True)
class RiskConfig:
    maximum_exposure: float = 1.0
    volatility_control: bool = True
    volatility_caps: tuple = (1., 1., .6, .2)
    volatility_percentiles: tuple = (.25, .75, .95)
    volatility_lookback: int = 252
    drawdown_edges: tuple = (.05, .10, .20, .30)
    maximum_turnover: float = 20.
    minimum_trades: int = 2
    minimum_validation_samples: int = 40
    maximum_fallback_fraction: float = .8

    def __post_init__(self):
        for name in ("maximum_exposure", "maximum_fallback_fraction"):
            fraction(name, getattr(self, name))
        for name, size in (("volatility_caps", 4), ("volatility_percentiles", 3), ("drawdown_edges", 4)):
            values = tuple(getattr(self, name))
            object.__setattr__(self, name, values)
            if len(values) != size:
                raise ValueError(f"{name} requires {size} values")
            for value in values:
                fraction(name, value)
        if any(a >= b for a, b in zip(self.volatility_percentiles, self.volatility_percentiles[1:])):
            raise ValueError("volatility percentiles must increase")
        if any(a >= b for a, b in zip(self.drawdown_edges, self.drawdown_edges[1:])):
            raise ValueError("drawdown edges must increase")
        if any(a < b for a, b in zip(self.volatility_caps, self.volatility_caps[1:])):
            raise ValueError("volatility caps must not increase with risk")
        integer("volatility_lookback", self.volatility_lookback, 20, 1260)
        integer("minimum_trades", self.minimum_trades, 1, 1000)
        integer("minimum_validation_samples", self.minimum_validation_samples, 10, 1000)
        if not math.isfinite(self.maximum_turnover) or not 0 < self.maximum_turnover <= 1000:
            raise ValueError("maximum_turnover must be in (0,1000]")
        if type(self.volatility_control) is not bool:
            raise ValueError("volatility_control must be boolean")


def fraction(name, value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be a finite fraction in [0,1]")


def integer(name, value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low},{high}]")


@dataclass(frozen=True)
class ExecutionConfig:
    cost_pct_per_side: float = .1
    slippage_pct: float = .02
    volatility_slippage_factor: float = 0.
    liquidity_slippage_factor: float = 0.
    cash_yield: float = 0.
    min_trade_gap_bars: int = 5
    buy_spacing_bars: int = 20
    max_entry_gap_atr: float | None = 1.
    stop_multiple_atr: float | None = 3.
    trail_multiple_atr: float | None = 4.
    delay_bars: int = 0
    entry_worsening: float = 0.
    exit_worsening: float = 0.
    skip_every: int = 0

    def __post_init__(self):
        for name in ("cost_pct_per_side", "slippage_pct", "volatility_slippage_factor",
                     "liquidity_slippage_factor", "cash_yield", "entry_worsening", "exit_worsening"):
            fraction(name, getattr(self, name))
        if self.slippage_pct > self.cost_pct_per_side:
            raise ValueError("slippage_pct is a component of cost_pct_per_side, not an additional cost")
        for name in ("min_trade_gap_bars", "buy_spacing_bars"):
            integer(name, getattr(self, name), 1, 365)
        integer("delay_bars", self.delay_bars, 0, 5)
        integer("skip_every", self.skip_every, 0, 100)
        for name in ("max_entry_gap_atr", "stop_multiple_atr", "trail_multiple_atr"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or not 0 < value <= 20):
                raise ValueError(f"{name} must be null or in (0,20]")


@dataclass(frozen=True)
class ACESConfig:
    version: int = ACES_VERSION
    enabled: bool = True
    initial_budget: float = 10000.
    buy_thresholds: tuple = (4, 5, 6, 7, 8)
    sell_thresholds: tuple = (-4, -5, -6, -7, -8)
    policy_mode: str = "COMPARE"
    purge_bars: int = 252
    q_finalists: int = 3
    minimum_plateau_fraction: float = .5
    stress_return_tolerance: float = .05
    allocation: AllocationConfig = field(default_factory=lambda: AllocationConfig(
        state=StateConfig(use_regime=True), economic=EconomicConfig(benchmark_missing_policy="BLOCK")))
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)

    def __post_init__(self):
        if type(self.version) is not int or self.version != ACES_VERSION or type(self.enabled) is not bool:
            raise ValueError("unknown ACES version or invalid enabled flag")
        if not math.isfinite(self.initial_budget) or not 0 < self.initial_budget <= 1e12:
            raise ValueError("initial_budget must be positive and at most 1e12")
        if self.policy_mode not in {"FIXED", "TUNED_FIXED", "Q_LEARNING", "COMPARE"}:
            raise ValueError("invalid ACES policy_mode")
        for name, sign in (("buy_thresholds", 1), ("sell_thresholds", -1)):
            values = tuple(getattr(self, name))
            object.__setattr__(self, name, values)
            if not 1 <= len(values) <= 7 or len(set(values)) != len(values):
                raise ValueError(f"{name} requires 1–7 unique thresholds")
            for value in values:
                integer(name, value * sign, 1, 30)
        integer("purge_bars", self.purge_bars, 1, 1260)
        integer("q_finalists", self.q_finalists, 1, 5)
        fraction("minimum_plateau_fraction", self.minimum_plateau_fraction)
        fraction("stress_return_tolerance", self.stress_return_tolerance)
        if self.allocation.q.minimum_visit_count < 1:
            raise ValueError("ACES minimum Q visits must be at least one")
        if self.allocation.state.use_regime is not True:
            raise ValueError("ACES requires allocation.state.use_regime=true")

    @classmethod
    def from_dict(cls, values=None):
        if values is not None and not isinstance(values, dict):
            raise ValueError("aces_config must be an object")
        values = dict(values or {})
        try:
            allocation = dict(values.get("allocation", {}))
            economic = dict(allocation.get("economic", {}))
            economic.setdefault("benchmark_missing_policy", "BLOCK")
            allocation["economic"] = economic
            state = dict(allocation.get("state", {}))
            state.setdefault("use_regime", True)
            allocation["state"] = state
            values["allocation"] = AllocationConfig.from_dict(allocation)
            values["risk"] = RiskConfig(**values.get("risk", {}))
            values["execution"] = ExecutionConfig(**values.get("execution", {}))
            return cls(**values)
        except TypeError as error:
            raise ValueError(f"invalid ACES configuration: {error}") from error

    def to_dict(self):
        return asdict(self)
