"""Causal, quarter-anchored two-week execution for the macro strategy router.

The shared Auto Tune simulator remains the only fill/position implementation.
Each window starts flat, accepts only signals inside that window, fills at the
next open, and closes any remaining position at the window's final close. A
10-bar entry cooldown inside an at-most-10-bar segment prohibits re-entry.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
import math
import random
from typing import Any, Dict, List, Optional, Sequence

from src.core import trading_calendar
from src.services.allocation.economic_reward import (
    BenchmarkSeries,
    EconomicConfig,
    evaluate_economic_reward,
)
from src.services.indicator_optimizer import (
    ATR_STOP_GRID,
    ATR_TRAIL_GRID,
    MIN_TRADE_GAP_BARS,
    SAMPLED_CANDIDATES,
    TOP_K,
    TUNABLE_SCOPES,
    WARMUP_BARS,
    _default_tunable,
    _param_distance,
    _sample_tunable,
)
from src.services.strategy_backtester import (
    DEFAULT_COST_PCT_PER_SIDE,
    compute_composite_signals,
    prepare_base_series,
    simulate_trades,
)
from src.services.strategy_engine import GENERATIONS


WINDOW_BARS = 10
MIN_TECHNICAL_TRAIN_WINDOWS = 12
TECHNICAL_VALIDATION_WINDOWS = 6
FAMILY_KEYS = tuple(generation["key"] for generation in GENERATIONS)


class MacroExecutionUnavailable(ValueError):
    """Expected input/calendar failure that disables only the optional router."""


def quarter_key(day: str) -> str:
    parsed = date.fromisoformat(day)
    return f"{parsed.year}Q{(parsed.month - 1) // 3 + 1}"


def _quarter_end(quarter: str) -> date:
    year, number = quarter.split("Q")
    month = int(number) * 3 + 1
    return date(int(year) + (month == 13), 1 if month == 13 else month, 1)


def _max_drawdown(equity: Sequence[float]) -> float:
    peak, drawdown = 1.0, 0.0
    for nav in equity:
        peak = max(peak, nav)
        drawdown = max(drawdown, 1.0 - nav / peak)
    return drawdown


def _family_candidates(family: str, count: int) -> List[Dict[str, Any]]:
    """Use the existing family grids with a fixed, data-independent search budget."""
    generation = next((item for item in GENERATIONS if item["key"] == family), None)
    if generation is None:
        raise ValueError(f"Unknown strategy family: {family}")
    scope = TUNABLE_SCOPES[family]
    candidates = [{"thresholds": _default_tunable(scope)}]
    if generation["atr_risk"]:
        candidates[0].update(stop_multiple_atr=ATR_STOP_GRID[len(ATR_STOP_GRID) // 2],
                             trail_multiple_atr=ATR_TRAIL_GRID[len(ATR_TRAIL_GRID) // 2])
    if not generation["tuned"]:
        return candidates
    rng = random.Random(FAMILY_KEYS.index(family))
    for _ in range(count - 1):
        candidate = {"thresholds": _sample_tunable(rng, scope)}
        if generation["atr_risk"]:
            candidate.update(stop_multiple_atr=rng.choice(ATR_STOP_GRID),
                             trail_multiple_atr=rng.choice(ATR_TRAIL_GRID))
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


class MacroExecutionEngine:
    """Walk forward within each family, independently of the macro routing model.

    Candidate selection uses only previously completed windows. The shared Auto
    Tune sampling budget is fixed before looking at prices; A stays unchanged.
    Older windows rank candidates, and the latest six select the training
    shortlist. With less than 12 training plus six validation windows, defaults
    remain in force and the selection metadata explains the missing history.
    All candidate simulations use the same costs, sizing, cooldown and ATR rules
    as Auto Tune. A missing stock session invalidates its entire window instead
    of stretching a two-week window across a missing observation.

    The existing XNYS calendar defines sessions, independently of data coverage.
    ``benchmark`` supplies adjusted US-session prices. Without it, exploratory
    execution is available, but no quarter is eligible for macro training.
    """

    def __init__(
        self,
        bars: Sequence[Dict[str, Any]],
        *,
        benchmark: Optional[BenchmarkSeries] = None,
        economic_config: Optional[EconomicConfig] = None,
        cost_pct_per_side: float = DEFAULT_COST_PCT_PER_SIDE,
        candidate_count: int = SAMPLED_CANDIDATES + 1,
        lookback_windows: int = 24,
        warmup_bars: int = WARMUP_BARS,
        as_of: Optional[date] = None,
    ) -> None:
        if not bars:
            raise MacroExecutionUnavailable("Macro execution requires daily bars")
        if type(candidate_count) is not int or not 1 <= candidate_count <= SAMPLED_CANDIDATES + 1:
            raise MacroExecutionUnavailable(
                f"candidate_count must be an integer in [1, {SAMPLED_CANDIDATES + 1}]")
        if type(lookback_windows) is not int or not 1 <= lookback_windows <= 252:
            raise MacroExecutionUnavailable("lookback_windows must be an integer in [1, 252]")
        if type(warmup_bars) is not int or warmup_bars < 0:
            raise MacroExecutionUnavailable("warmup_bars must be a nonnegative integer")
        if not math.isfinite(cost_pct_per_side) or not 0 <= cost_pct_per_side < 100:
            raise MacroExecutionUnavailable("cost_pct_per_side must be finite and in [0, 100)")
        try:
            self.as_of = as_of or date.fromisoformat(str(bars[-1]["date"]))
            if isinstance(self.as_of, str):
                self.as_of = date.fromisoformat(self.as_of)
            self.bars = [dict(bar) for bar in bars if str(bar["date"]) <= self.as_of.isoformat()]
            for bar in self.bars:
                date.fromisoformat(str(bar["date"]))
                prices = [float(bar[key]) for key in ("open", "high", "low", "close")]
                if any(not math.isfinite(value) or value <= 0 for value in prices):
                    raise ValueError("OHLC prices must be positive and finite")
                if prices[1] < max(prices[0], prices[3]) or prices[2] > min(prices[0], prices[3]):
                    raise ValueError("OHLC high/low must bound open and close")
        except (KeyError, TypeError, ValueError) as exc:
            raise MacroExecutionUnavailable(f"Invalid daily bars: {exc}") from exc
        if not self.bars:
            raise MacroExecutionUnavailable("No bars available on or before as_of")
        self.dates = [str(bar["date"]) for bar in self.bars]
        if self.dates != sorted(set(self.dates)):
            raise MacroExecutionUnavailable("Bars must have unique chronological dates")
        self.base = prepare_base_series(self.bars)
        self.benchmark = benchmark
        self.config = economic_config or EconomicConfig()
        self.cost = cost_pct_per_side
        self.lookback_windows = lookback_windows
        self.candidates = {family: _family_candidates(family, candidate_count) for family in FAMILY_KEYS}
        self._signals: Dict[Any, Any] = {}
        self._simulations: Dict[Any, Any] = {}
        self._selections: Dict[Any, Any] = {}
        self._quarter_windows: Dict[str, Any] = {}
        self.windows: List[Dict[str, Any]] = []
        self.current_window_start = self.dates[-1]
        try:
            self._prepare_windows(warmup_bars)
        except (ValueError, RuntimeError) as exc:
            raise MacroExecutionUnavailable(f"NYSE session calendar unavailable: {exc}") from exc

    def _prepare_windows(self, warmup_bars: int) -> None:
        if not trading_calendar._XCALS_AVAILABLE:
            raise RuntimeError("Trading calendar is unavailable")
        first = date.fromisoformat(self.dates[0])
        start = first.replace(month=((first.month - 1) // 3) * 3 + 1, day=1)
        calendar = trading_calendar.xcals.get_calendar(trading_calendar.MARKET_EXCHANGE["us"])
        reference = [session.date().isoformat()
                     for session in calendar.sessions_in_range(start, self.as_of)]
        self.session_dates = reference
        if not reference:
            return
        groups = defaultdict(list)
        for day in reference:
            groups[quarter_key(day)].append(day)
        positions = {day: index for index, day in enumerate(self.dates)}
        for quarter, sessions in groups.items():
            # The whole quarter must have indicator warmup before its first day.
            if bisect_left(self.dates, sessions[0]) < warmup_bars:
                continue
            ended = self.as_of >= _quarter_end(quarter)
            complete = ended and self.benchmark is not None
            quarter_windows = []
            for offset in range(0, len(sessions), WINDOW_BARS):
                days = sessions[offset:offset + WINDOW_BARS]
                if len(days) < WINDOW_BARS and not ended:
                    continue
                indices = [positions.get(day) for day in days]
                benchmark_missing = self.benchmark is not None and not self.benchmark.covers(days)
                if any(index is None for index in indices) or benchmark_missing:
                    complete = False
                    continue
                start, end = indices[0], indices[-1]
                if self.dates[start:end + 1] != days:
                    complete = False
                    continue
                window = dict(quarter=quarter, start_index=start, end_index=end,
                              start_date=days[0], end_date=days[-1], trading_bars=len(days),
                              short_quarter_tail=len(days) < WINDOW_BARS)
                quarter_windows.append(window)
                self.windows.append(window)
            if quarter_windows:
                self._quarter_windows[quarter] = dict(
                    quarter=quarter, start_date=sessions[0], end_date=sessions[-1],
                    complete=complete, session_calendar_verified=True,
                    windows=quarter_windows,
                )
        # Select the still-active or upcoming window, even immediately after the
        # tenth session closes. A just-finished window must not freeze next
        # window's parameters at an obsolete training cutoff.
        current_start = self.as_of.replace(month=((self.as_of.month - 1) // 3) * 3 + 1, day=1)
        next_quarter = _quarter_end(quarter_key(self.as_of.isoformat()))
        current_sessions = [session.date().isoformat() for session in calendar.sessions_in_range(
            current_start, next_quarter - timedelta(days=1))]
        for offset in range(0, len(current_sessions), WINDOW_BARS):
            days = current_sessions[offset:offset + WINDOW_BARS]
            if days[-1] >= self.as_of.isoformat() and days[-1] > self.dates[-1]:
                self.current_window_start = days[0]
                break
        else:
            self.current_window_start = calendar.date_to_session(next_quarter, direction="next").date().isoformat()

    def _simulate(self, family: str, candidate_index: int, window: Dict[str, Any]) -> Dict[str, Any]:
        key = (family, candidate_index, window["start_index"], window["end_index"])
        if key not in self._simulations:
            candidate = self.candidates[family][candidate_index]
            signal_key = tuple(sorted(candidate["thresholds"].items()))
            if signal_key not in self._signals:
                self._signals[signal_key] = compute_composite_signals(self.base, candidate["thresholds"])
            generation = next(item for item in GENERATIONS if item["key"] == family)
            self._simulations[key] = simulate_trades(
                self.base, self._signals[signal_key], window["start_index"], window["end_index"],
                window_days=WINDOW_BARS, cost_pct_per_side=self.cost,
                use_trend_filter=generation["trend_filter"], use_volume_filter=generation["volume_filter"],
                stop_multiple_atr=candidate.get("stop_multiple_atr"),
                trail_multiple_atr=candidate.get("trail_multiple_atr"),
                size_by_score=True, min_trade_gap_bars=MIN_TRADE_GAP_BARS,
            )
        return self._simulations[key]

    def _metrics(self, equity: Sequence[float], start: str, end: str, trade_count: int) -> Dict[str, Any]:
        reward = evaluate_economic_reward(start, end, 1.0, equity[-1], initial_date=start,
                                          config=self.config, benchmark=self.benchmark)
        cash = evaluate_economic_reward(start, end, 1.0, 1.0, initial_date=start,
                                        config=self.config, benchmark=self.benchmark)
        drawdown = _max_drawdown(equity)
        drawdown_penalty = drawdown + max(0.0, drawdown - self.config.allowed_max_drawdown)
        raw = reward["portfolio_log_return"] + reward["benchmark_reward"] - reward["cagr_penalty"]
        cash_raw = cash["benchmark_reward"] - cash["cagr_penalty"]
        benchmark_return = reward["benchmark_return"]
        return dict(
            utility=raw - cash_raw - drawdown_penalty,
            return_pct=(equity[-1] - 1.0) * 100,
            max_drawdown_pct=drawdown * 100, trade_count=trade_count,
            benchmark_return_pct=None if benchmark_return is None else benchmark_return * 100,
            relative_alpha_pct=(None if benchmark_return is None
                                else (equity[-1] - 1.0 - benchmark_return) * 100),
            target_cagr=self.config.target_cagr, required_nav=reward["required_nav"],
            cagr_penalty=reward["cagr_penalty"], drawdown_penalty=drawdown_penalty,
            benchmark_reward_reason=reward["benchmark_reward_reason"],
        )

    def _combine(self, windows: Sequence[Dict[str, Any]], simulations: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        equity, nav, trade_count, holding_bars = [], 1.0, 0, 0
        dates = []
        cursor = bisect_left(self.session_dates, windows[0]["start_date"])
        for window, simulation in zip(windows, simulations):
            start = bisect_left(self.session_dates, window["start_date"])
            end = bisect_left(self.session_dates, window["end_date"])
            # Unobservable windows are excluded from trading. Keep their known
            # exchange sessions explicitly in cash so rewards/equity retain the
            # same elapsed interval as the benchmark and CAGR hurdle.
            equity.extend([nav] * (start - cursor))
            dates.extend(self.session_dates[cursor:end + 1])
            equity.extend(nav * value for value in simulation["equity"])
            nav = equity[-1]
            trade_count += len(simulation["trades"])
            holding_bars += simulation["holding_bars"]
            cursor = end + 1
        return dict(self._metrics(equity, windows[0]["start_date"], windows[-1]["end_date"], trade_count),
                    equity=equity, dates=dates, holding_bars=holding_bars)

    def parameters_for(self, family: str, before_date: Optional[str] = None) -> Dict[str, Any]:
        """Parameters selected exclusively from windows ending before the cutoff."""
        if family == "CASH":
            return dict(family="CASH", candidate_index=None, params={}, trained_through=None,
                        training_windows=0, candidate_count=0, selection_method="cash",
                        fit_windows=0, validation_windows=0, fit_through=None,
                        validation_start=None, validation_through=None, validation_utility=None)
        if family not in self.candidates:
            raise ValueError(f"Unknown strategy family: {family}")
        cutoff = before_date or self.current_window_start
        date.fromisoformat(cutoff)
        key = family, cutoff
        if key not in self._selections:
            training = [window for window in self.windows if window["end_date"] < cutoff][-self.lookback_windows:]
            best, score, validation_score = 0, None, None
            fit, validation = [], []
            method = "baseline" if len(self.candidates[family]) == 1 else "default_insufficient_history"
            if len(self.candidates[family]) > 1 and len(training) >= (
                    MIN_TECHNICAL_TRAIN_WINDOWS + TECHNICAL_VALIDATION_WINDOWS):
                fit, validation = training[:-TECHNICAL_VALIDATION_WINDOWS], training[-TECHNICAL_VALIDATION_WINDOWS:]
                scores = []
                for index in range(len(self.candidates[family])):
                    simulations = [self._simulate(family, index, window) for window in fit]
                    scores.append(self._combine(fit, simulations)["utility"])
                shortlist = sorted(range(len(scores)), key=lambda index: (-scores[index], index))[:TOP_K]
                # Always retain the unchanged family default as a validation
                # comparator, even if training noise excluded it from Top-K.
                if 0 not in shortlist:
                    shortlist.append(0)
                validation_scores = {
                    index: self._combine(validation, [self._simulate(family, index, window)
                                                     for window in validation])["utility"]
                    for index in shortlist
                }
                best = min(shortlist, key=lambda index: (
                    -validation_scores[index], -scores[index],
                    _param_distance(self.candidates[family][index]["thresholds"], TUNABLE_SCOPES[family]), index,
                ))
                score = scores[best]
                validation_score = validation_scores[best]
                method = "chronological_train_validation"
            self._selections[key] = dict(
                family=family, candidate_index=best, params=deepcopy(self.candidates[family][best]),
                trained_through=training[-1]["end_date"] if training else None,
                training_windows=len(training), candidate_count=len(self.candidates[family]),
                training_utility=score, validation_utility=validation_score, selection_method=method,
                fit_windows=len(fit), validation_windows=len(validation),
                fit_through=fit[-1]["end_date"] if fit else None,
                validation_start=validation[0]["start_date"] if validation else None,
                validation_through=validation[-1]["end_date"] if validation else None,
            )
        return deepcopy(self._selections[key])

    def quarterly_outcomes(self) -> List[Dict[str, Any]]:
        """Out-of-sample family outcomes; only ``complete`` quarters are labels."""
        rows = []
        for metadata in self._quarter_windows.values():
            windows = metadata["windows"]
            families = {}
            for family in FAMILY_KEYS:
                simulations, reports = [], []
                for window in windows:
                    selection = self.parameters_for(family, window["start_date"])
                    simulation = self._simulate(family, selection["candidate_index"], window)
                    simulations.append(simulation)
                    reports.append(dict(window, **selection, trades=deepcopy(simulation["trades"]),
                                        decisions=deepcopy(simulation["decisions"]), equity=list(simulation["equity"]),
                                        holding_bars=simulation["holding_bars"],
                                        **self._metrics(simulation["equity"], window["start_date"],
                                                        window["end_date"], len(simulation["trades"]))))
                families[family] = dict(self._combine(windows, simulations), windows=reports)
            first, last = windows[0]["start_date"], windows[-1]["end_date"]
            days = families[FAMILY_KEYS[0]]["dates"]
            count = len(days)
            families["CASH"] = dict(self._metrics([1.0] * count, first, last, 0),
                                    equity=[1.0] * count, windows=[], holding_bars=0)
            if self.benchmark is not None and self.benchmark.covers(days):
                initial = self.benchmark.values[first]
                equity = [self.benchmark.values[day] / initial for day in days]
                families["SPY_BuyHold"] = dict(self._metrics(equity, first, last, 0),
                                             equity=equity, windows=[], holding_bars=count)
            rows.append({key: value for key, value in metadata.items() if key != "windows"})
            rows[-1].update(families=families, dates=days, completed_windows=len(windows),
                            window_bars=WINDOW_BARS,
                            benchmark_complete=self.benchmark is not None and self.benchmark.covers(days))
        return rows
