"""Outcome-only time-value and exactly aligned total-return benchmark rewards."""

from dataclasses import dataclass
from datetime import date
import math
from types import MappingProxyType


@dataclass(frozen=True)
class EconomicConfig:
    target_cagr: float = .30
    lambda_cagr: float = .25
    lambda_alpha: float = 1.0
    lambda_underperform: float = .5
    alpha_reward_cap: float = .05
    alpha_penalty_cap: float = .05
    alpha_margin: float = 0.0
    minimum_cagr_days: int = 90
    allowed_max_drawdown: float = .15
    benchmark_missing_policy: str = "DISABLE"

    def __post_init__(self):
        for name in ("target_cagr", "lambda_cagr", "lambda_alpha", "lambda_underperform",
                     "alpha_reward_cap", "alpha_penalty_cap", "alpha_margin", "allowed_max_drawdown"):
            value = getattr(self, name)
            if not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite and in [0, 1]")
        if type(self.minimum_cagr_days) is not int or not 1 <= self.minimum_cagr_days <= 3650:
            raise ValueError("minimum_cagr_days must be an integer in [1, 3650]")
        if self.benchmark_missing_policy not in {"BLOCK", "DISABLE"}:
            raise ValueError("benchmark_missing_policy must be BLOCK or DISABLE")


class BenchmarkDataMissing(ValueError):
    pass


class BenchmarkSeries:
    """Immutable, explicitly adjusted US-session-close observations. No filling."""

    def __init__(self, values, *, symbol="SPY", adjusted=False, session="US_SESSION_CLOSE"):
        if not adjusted:
            raise ValueError("benchmark requires adjusted total-return prices")
        if session != "US_SESSION_CLOSE":
            raise ValueError("benchmark session must match strategy US session closes")
        for day, price in values.items():
            date.fromisoformat(day)
            if not math.isfinite(price) or price <= 0:
                raise ValueError("benchmark prices must be positive and finite")
        self.values = MappingProxyType(dict(values))
        self.symbol, self.session = symbol, session

    def covers(self, dates):
        return all(day in self.values for day in dates)


def cagr_snapshot(initial_nav, nav, elapsed_days, config):
    if initial_nav <= 0 or nav <= 0 or elapsed_days < 0:
        raise ValueError("invalid CAGR evaluation")
    required = initial_nav * math.exp(math.log1p(config.target_cagr) * elapsed_days / 365.25)
    deficit = max(0., math.log(required / nav))
    actual = (math.expm1(math.log(nav / initial_nav) * 365.25 / elapsed_days)
              if elapsed_days >= config.minimum_cagr_days else None)
    return dict(elapsed_days=elapsed_days, actual_nav=nav, required_nav_for_30pct_cagr=required,
                required_nav=required, actual_cagr=actual, target_cagr=config.target_cagr,
                current_cagr_deficit=deficit)


def benchmark_component(portfolio_log_return, benchmark_log_return, config):
    alpha = portfolio_log_return - benchmark_log_return
    if alpha > config.alpha_margin:
        return config.lambda_alpha * min(alpha, config.alpha_reward_cap), (
            "BEAT_BENCHMARK_IN_DECLINE" if portfolio_log_return < 0 else "BEAT_BENCHMARK")
    if portfolio_log_return > 0:
        return 0., "PROFIT_BUT_TRAILED_BENCHMARK"
    return -config.lambda_underperform * min(max(0., -alpha), config.alpha_penalty_cap), (
        "UNDERPERFORMED_BENCHMARK" if alpha < 0 else "NO_MEANINGFUL_ALPHA")


def evaluate_economic_reward(start_date, end_date, nav_before, nav_next, *, initial_date,
                             initial_nav=1., config=None, benchmark=None):
    config = config or EconomicConfig()
    elapsed_before = (date.fromisoformat(start_date) - date.fromisoformat(initial_date)).days
    elapsed = (date.fromisoformat(end_date) - date.fromisoformat(initial_date)).days
    if elapsed < elapsed_before:
        raise ValueError("evaluation timestamps must be chronological")
    before = cagr_snapshot(initial_nav, nav_before, elapsed_before, config)
    result = cagr_snapshot(initial_nav, nav_next, elapsed, config)
    increase = max(0., result["current_cagr_deficit"] - before["current_cagr_deficit"])
    portfolio_log = math.log(nav_next / nav_before)
    result.update(previous_cagr_deficit=before["current_cagr_deficit"], cagr_deficit_increase=increase,
                  cagr_penalty=config.lambda_cagr * increase,
                  portfolio_return=nav_next / nav_before - 1, portfolio_log_return=portfolio_log,
                  benchmark_start_timestamp=start_date, benchmark_end_timestamp=end_date,
                  benchmark_session="US_SESSION_CLOSE", benchmark_symbol=benchmark.symbol if benchmark else "SPY",
                  benchmark_start_value=None, benchmark_end_value=None, benchmark_return=None,
                  benchmark_log_return=None, relative_alpha=None, benchmark_reward=0.,
                  benchmark_reward_reason="BENCHMARK_DATA_MISSING")
    if benchmark is None or not benchmark.covers((start_date, end_date)):
        if config.benchmark_missing_policy == "BLOCK":
            raise BenchmarkDataMissing("BENCHMARK_DATA_MISSING: exact adjusted benchmark dates required")
        return result
    first, last = benchmark.values[start_date], benchmark.values[end_date]
    bench_log = math.log(last / first)
    component, reason = benchmark_component(portfolio_log, bench_log, config)
    result.update(benchmark_start_value=first, benchmark_end_value=last,
                  benchmark_return=last / first - 1, benchmark_log_return=bench_log,
                  relative_alpha=portfolio_log - bench_log, benchmark_reward=component,
                  benchmark_reward_reason=reason)
    return result
