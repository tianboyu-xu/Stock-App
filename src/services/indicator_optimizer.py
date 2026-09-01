# -*- coding: utf-8 -*-
"""指标阈值调优与触发器收益模拟。

包含两部分：

1. `simulate_transactions` / `calculate_trigger_benefits`：
   技术指标接口的触发器累计收益曲线仍使用（每个窗口最多一次买卖的简单模拟）。
2. `run_auto_tune`：
   技术指标图 "Auto Tune" 的参数寻优入口。基于 strategy_backtester
   的确定性回测引擎，把历史按 训练/验证/测试 划分（测试段长度可选，
   默认 5 年，从尾部预留；训练/验证在剩余历史按 60:20 相对比例划分）：
   训练段搜索参数、验证段选择候选、测试段只用于报告样本外表现。
   目标函数平衡收益、回撤、风险调整收益、交易质量与信号频率，
   不单独最大化历史收益率。评分逻辑保持不变，只调参数。
   另附三个同窗口基准（个股/标普500 买入持有、推荐策略时点套用标普500）；
   税后指标按美国资本利得税近似，税率区分短期（普通所得）与长期。

策略代际（从简到繁）：
    A: 基线 —— 当前复合评分规则 + 默认阈值
    B: A + 趋势过滤（Close > SMA200 且 SMA200 上行才允许买入）
    C: B + ATR 止损 / ATR 移动止盈
    D: 最终评分策略 —— 全参数寻优 + 趋势过滤 + 成交量确认 + ATR 风控
    E: 多因子评分 —— 经典评分 + BOLL/CCI/DMI/MFI/量能/52 周位置因子
       权重与触发水平寻优，无额外过滤
    F: 多因子 + 风控 —— E + 趋势过滤 + 成交量确认 + ATR 风控

A–D 只调经典参数（新因子权重恒为 0，结果与改造前逐位一致）；
E/F 在经典参数之外同时调新因子权重与触发水平。

选择原则：验证段目标函数与最优差距在 EPS_SIMPLICITY 内时，
优先选择更简单的代际；若更复杂的代际没有带来足够的样本外改善，
则保留简单策略。
"""

from __future__ import annotations

import random
from bisect import bisect_left, bisect_right
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.services.indicator_service import DEFAULT_THRESHOLDS
from src.services.strategy_backtester import (
    DEFAULT_COST_PCT_PER_SIDE,
    DEFAULT_LONG_TERM_TAX_PCT,
    DEFAULT_SHORT_TERM_TAX_PCT,
    TRADING_DAYS_PER_YEAR,
    compute_composite_signals,
    objective_score,
    prepare_base_series,
    simulate_buy_hold,
    simulate_trades,
    summarize_metrics,
    timing_signals_from_trades,
)

TRIGGER_LABELS = {
    "macd": "MACD",
    "kdj": "KDJ",
    "rsi": "RSI",
    "obv": "OBV",
    "boll": "BOLL",
    "cci": "CCI",
    "dmi": "DMI",
    "mfi": "MFI",
}


def simulate_transactions(
    dates: Sequence[str],
    close: Sequence[float],
    triggers: Dict[str, Sequence[float | None]],
    window_days: int,
) -> Dict[str, Any]:
    """Simulate non-overlapping windows with at most one buy and sell each."""
    n = len(close)
    benefit_series: List[float | None] = [None] * n
    transactions: List[Dict[str, Any]] = []
    accumulated = 1.0
    for start in range(0, n, window_days):
        end = min(start + window_days, n)
        buy_index = next((i for i in range(start, end) if triggers["buy"][i] is not None), None)
        if buy_index is None:
            continue
        sell_index = next((i for i in range(buy_index + 1, end) if triggers["sell"][i] is not None), None)
        if sell_index is None or close[buy_index] <= 0:
            continue
        buy_price = float(triggers["buy"][buy_index] or close[buy_index])
        sell_price = float(triggers["sell"][sell_index] or close[sell_index])
        benefit = (sell_price / buy_price - 1.0) * 100.0
        accumulated *= 1.0 + benefit / 100.0
        for index in range(sell_index, end):
            benefit_series[index] = (accumulated - 1.0) * 100.0
        transactions.append({
            "buy_date": dates[buy_index], "sell_date": dates[sell_index],
            "buy_price": buy_price, "sell_price": sell_price, "benefit_pct": benefit,
        })
    return {
        "benefit_series": benefit_series,
        "accumulated_benefit_pct": (accumulated - 1.0) * 100.0,
        "transactions": transactions,
    }


def calculate_trigger_benefits(
    computed: Dict[str, Any], window_days: int,
) -> Dict[str, Dict[str, Any]]:
    """Calculate an aligned cumulative benefit curve for every trigger group."""
    output: Dict[str, Dict[str, Any]] = {}
    for trigger, label in TRIGGER_LABELS.items():
        raw = computed["triggers"]
        output[trigger] = simulate_transactions(
            computed["dates"],
            computed["close"],
            {"buy": raw[f"{trigger}_buy"], "sell": raw[f"{trigger}_sell"]},
            window_days,
        )
        output[trigger]["label"] = label
    return output


# ---------------------------------------------------------------------------
# Auto Tune（多策略代际参数寻优）
# ---------------------------------------------------------------------------

# 可调参数网格（均包含默认值）。只调参数，不改评分逻辑；
# RSI/KDJ/MACD 的周期类参数不参与寻优（见 fixed_parameters）。
TUNABLE_GRID: Dict[str, List[float]] = {
    "composite_buy_threshold": [3.0, 4.0, 5.0, 6.0, 7.0],
    "composite_sell_threshold": [3.0, 4.0, 5.0, 6.0],
    "rsi_low": [10, 15, 20, 25, 30],
    "rsi_high": [70, 75, 80, 85, 90],
    "kdj_low": [20, 30, 35, 40, 50],
    "kdj_high": [60, 70, 75, 80, 85],
    "macd_lookback": [60, 90, 120, 150, 180],
    "macd_low_percentile": [5, 10, 15, 20],
    "macd_high_percentile": [80, 85, 90, 95],
    "trend_period": [20, 50, 120, 200],
    # --- 扩展因子（BOLL/CCI/DMI/MFI/量能/52 周位置），追加在经典键之后 ---
    "boll_buy_level": [0.05, 0.1, 0.15, 0.2],
    "boll_sell_level": [0.8, 0.85, 0.9, 0.95],
    "boll_weight": [0, 1, 2],
    "cci_buy_level": [-150.0, -120.0, -100.0, -80.0],
    "cci_sell_level": [80.0, 100.0, 120.0, 150.0],
    "cci_weight": [0, 1, 2],
    "adx_min_level": [15.0, 20.0, 25.0, 30.0],
    "dmi_weight": [0, 1, 2],
    "mfi_buy_level": [15.0, 20.0, 25.0, 30.0],
    "mfi_sell_level": [70.0, 75.0, 80.0, 85.0],
    "mfi_weight": [0, 1, 2],
    "volume_confirm_level": [1.2, 1.5, 2.0, 2.5],
    "volume_weight": [0, 1, 2],
    "range52_high_level": [0.85, 0.9, 0.95, 1.0],
    "range52_low_level": [1.05, 1.1, 1.15, 1.2],
    "range52_weight": [0, 1, 2],
}

# 经典可调参数键（保持原始顺序：A–D 的 RNG 调用序列与改造前完全一致）
CLASSIC_TUNABLE_KEYS: Tuple[str, ...] = (
    "composite_buy_threshold",
    "composite_sell_threshold",
    "rsi_low",
    "rsi_high",
    "kdj_low",
    "kdj_high",
    "macd_lookback",
    "macd_low_percentile",
    "macd_high_percentile",
    "trend_period",
)

# 全部可调参数键（经典键在前，扩展因子键在后）
ALL_TUNABLE_KEYS: Tuple[str, ...] = tuple(TUNABLE_GRID)

# 按代际限定采样键集合：A–D 只调经典键（新因子权重恒 0，信号逐位不变）；
# E/F 调全部键（含新因子权重与触发水平）。
TUNABLE_SCOPES: Dict[str, Tuple[str, ...]] = {
    "A": CLASSIC_TUNABLE_KEYS,
    "B": CLASSIC_TUNABLE_KEYS,
    "C": CLASSIC_TUNABLE_KEYS,
    "D": CLASSIC_TUNABLE_KEYS,
    "E": ALL_TUNABLE_KEYS,
    "F": ALL_TUNABLE_KEYS,
}

ATR_STOP_GRID = [2.0, 2.5, 3.0]
ATR_TRAIL_GRID = [2.5, 3.0, 3.5]

# 推荐参数展示顺序（前端按 key 渲染标签）
PARAM_DISPLAY_ORDER = (
    "composite_buy_threshold",
    "composite_sell_threshold",
    "rsi_low",
    "rsi_high",
    "kdj_low",
    "kdj_high",
    "macd_lookback",
    "macd_low_percentile",
    "macd_high_percentile",
    "trend_period",
    "stop_multiple_atr",
    "trail_multiple_atr",
    "boll_buy_level",
    "boll_sell_level",
    "boll_weight",
    "cci_buy_level",
    "cci_sell_level",
    "cci_weight",
    "adx_min_level",
    "dmi_weight",
    "mfi_buy_level",
    "mfi_sell_level",
    "mfi_weight",
    "volume_confirm_level",
    "volume_weight",
    "range52_high_level",
    "range52_low_level",
    "range52_weight",
)

# 图表可直接加载的阈值键（对应前端 IndicatorThresholds 的复合部分）
CHART_THRESHOLD_KEYS = (
    "composite_buy_threshold",
    "composite_sell_threshold",
    "macd_lookback",
    "macd_low_percentile",
    "macd_high_percentile",
    "rsi_low",
    "rsi_high",
    "kdj_low",
    "kdj_high",
    "trend_period",
    "boll_buy_level",
    "boll_sell_level",
    "boll_weight",
    "cci_buy_level",
    "cci_sell_level",
    "cci_weight",
    "adx_min_level",
    "dmi_weight",
    "mfi_buy_level",
    "mfi_sell_level",
    "mfi_weight",
    "volume_confirm_level",
    "volume_weight",
    "range52_high_level",
    "range52_low_level",
    "range52_weight",
)

TRAIN_RATIO = 0.6
VALIDATION_RATIO = 0.2
WARMUP_BARS = 220          # 覆盖 SMA200 与最长 MACD 回看窗口，保证各段指标成熟度一致
MIN_TOTAL_BARS = 600       # 低于该值时训练/验证/测试都不再有统计意义
# 显式指定测试段年数时的边界：测试段最多占可用历史的 60%，
# 且训练+验证合计至少保留 MIN_TRAINVAL_BARS（约一年），防止某一段失去统计意义。
MAX_TEST_USABLE_RATIO = 0.6
MIN_TRAINVAL_BARS = 250
MIN_TRAIN_BARS = 60        # 用户裁剪训练段后允许的最小训练窗长度
SAMPLED_CANDIDATES = 48    # 默认候选之外的随机采样候选数
TOP_K = 8                  # 进入验证段复评的训练段最优候选数
HILL_CLIMB_SEEDS = 3       # 爬山搜索的种子候选数
HILL_CLIMB_SWEEPS = 2      # 爬山搜索的最大扫描轮数
EPS_SIMPLICITY = 0.05      # “足够好”容差：验证分差距小于该值即视为相当

# 基准对比：标普500 指数代码（走 YFinance 美股指数路由）与最少可用 bar 数。
BENCHMARK_INDEX_CODE = "^GSPC"
MIN_BENCHMARK_BARS = 60

GENERATIONS: Tuple[Dict[str, Any], ...] = (
    {
        "key": "A",
        "name_zh": "基线（当前规则）",
        "name_en": "Baseline (current rules)",
        "description_zh": "默认阈值的复合评分规则，无额外过滤。",
        "description_en": "Composite scoring with default thresholds, no extra filters.",
        "trend_filter": False,
        "volume_filter": False,
        "atr_risk": False,
        "tuned": False,
    },
    {
        "key": "B",
        "name_zh": "基线 + 趋势过滤",
        "name_en": "Baseline + trend filter",
        "description_zh": "仅当 Close > SMA200 且 SMA200 上行时才允许买入。",
        "description_en": "Entries require Close > SMA200 with SMA200 rising.",
        "trend_filter": True,
        "volume_filter": False,
        "atr_risk": False,
        "tuned": True,
    },
    {
        "key": "C",
        "name_zh": "趋势 + ATR 风控",
        "name_en": "Trend + ATR risk management",
        "description_zh": "在 B 基础上增加 ATR 止损与 ATR 移动止盈。",
        "description_en": "Adds an ATR stop-loss and ATR trailing exit on top of B.",
        "trend_filter": True,
        "volume_filter": False,
        "atr_risk": True,
        "tuned": True,
    },
    {
        "key": "D",
        "name_zh": "最终评分策略",
        "name_en": "Final scoring strategy",
        "description_zh": "全参数寻优 + 趋势过滤 + 成交量确认 + ATR 风控。",
        "description_en": "Full parameter search plus trend filter, volume confirmation and ATR risk management.",
        "trend_filter": True,
        "volume_filter": True,
        "atr_risk": True,
        "tuned": True,
    },
    {
        "key": "E",
        "name_zh": "多因子评分",
        "name_en": "Multi-factor scoring",
        "description_zh": "经典评分 + BOLL/CCI/DMI/MFI/量能/52 周位置因子权重与触发水平寻优，无额外过滤。",
        "description_en": "Classic scoring plus tuned weights/levels for BOLL, CCI, DMI, MFI, volume and 52-week-range factors, no extra filters.",
        "trend_filter": False,
        "volume_filter": False,
        "atr_risk": False,
        "tuned": True,
    },
    {
        "key": "F",
        "name_zh": "多因子 + 风控",
        "name_en": "Multi-factor + risk management",
        "description_zh": "在 E 基础上增加趋势过滤、成交量确认与 ATR 止损/移动止盈。",
        "description_en": "Adds trend filter, volume confirmation and ATR stop-loss/trailing exit on top of E.",
        "trend_filter": True,
        "volume_filter": True,
        "atr_risk": True,
        "tuned": True,
    },
)


_INT_TUNABLE_KEYS = frozenset(
    key for key, grid in TUNABLE_GRID.items()
    if all(isinstance(value, int) for value in grid)
)


def _coerce_param(key: str, value: Any) -> Any:
    if key in _INT_TUNABLE_KEYS:
        return int(round(float(value)))
    return float(value)


def _default_tunable(keys: Optional[Sequence[str]] = None) -> Dict[str, float]:
    """默认可调参数。``keys`` 为 None 时取全部可调键，否则只取给定键。"""
    selected = TUNABLE_GRID if keys is None else {key: TUNABLE_GRID[key] for key in keys}
    return {key: float(DEFAULT_THRESHOLDS[key]) for key in selected}


def _sample_tunable(
    rng: random.Random, keys: Optional[Sequence[str]] = None,
) -> Dict[str, float]:
    """随机采样可调参数。``keys`` 限定采样键集合（保持给定顺序）。"""
    selected = TUNABLE_GRID if keys is None else {key: TUNABLE_GRID[key] for key in keys}
    return {key: rng.choice(grid) for key, grid in selected.items()}


def _grid_index(grid: Sequence[float], value: Optional[float]) -> int:
    if value is None:
        return len(grid) // 2
    try:
        return grid.index(value)
    except ValueError:
        return len(grid) // 2


def _param_distance(
    thresholds: Dict[str, float], keys: Optional[Sequence[str]] = None,
) -> float:
    """参数相对默认值的归一化距离（平手时的次要 tie-break）。"""
    selected = TUNABLE_GRID if keys is None else {key: TUNABLE_GRID[key] for key in keys}
    total = 0.0
    for key, grid in selected.items():
        span = max(grid) - min(grid)
        total += abs(float(thresholds[key]) - float(DEFAULT_THRESHOLDS[key])) / span
    return total


class _GenerationEvaluator:
    """在同一份基础序列上评估某代际参数在各区间的表现（带信号缓存）。"""

    def __init__(
        self,
        base: Dict[str, Any],
        window_days: int,
        cost_pct_per_side: float,
        short_term_tax_pct: float = DEFAULT_SHORT_TERM_TAX_PCT,
        long_term_tax_pct: float = DEFAULT_LONG_TERM_TAX_PCT,
    ) -> None:
        self._base = base
        self._window_days = window_days
        self._cost = cost_pct_per_side
        self._tax_short = short_term_tax_pct
        self._tax_long = long_term_tax_pct
        self._signal_cache: Dict[Tuple[Tuple[str, float], ...], Dict[str, List[Any]]] = {}

    def signals(self, thresholds: Dict[str, float]) -> Dict[str, List[Any]]:
        key = tuple(sorted((k, float(v)) for k, v in thresholds.items()))
        cached = self._signal_cache.get(key)
        if cached is None:
            cached = compute_composite_signals(self._base, thresholds)
            self._signal_cache[key] = cached
        return cached

    def simulate(
        self,
        thresholds: Dict[str, float],
        start: int,
        end: int,
        gen: Dict[str, Any],
        stop_multiple_atr: Optional[float] = None,
        trail_multiple_atr: Optional[float] = None,
    ) -> Dict[str, Any]:
        return simulate_trades(
            self._base,
            self.signals(thresholds),
            start,
            end,
            window_days=self._window_days,
            cost_pct_per_side=self._cost,
            use_trend_filter=gen["trend_filter"],
            use_volume_filter=gen["volume_filter"],
            stop_multiple_atr=stop_multiple_atr,
            trail_multiple_atr=trail_multiple_atr,
        )

    def evaluate(
        self,
        thresholds: Dict[str, float],
        start: int,
        end: int,
        gen: Dict[str, Any],
        stop_multiple_atr: Optional[float] = None,
        trail_multiple_atr: Optional[float] = None,
    ) -> Tuple[Dict[str, Any], float]:
        simulation = self.simulate(
            thresholds, start, end, gen, stop_multiple_atr, trail_multiple_atr,
        )
        metrics = summarize_metrics(
            simulation, start, end,
            short_term_tax_pct=self._tax_short,
            long_term_tax_pct=self._tax_long,
        )
        years = (end - start + 1) / TRADING_DAYS_PER_YEAR
        return metrics, objective_score(metrics, years)


def _candidate_risk(
    candidate: Dict[str, Any], gen: Dict[str, Any],
) -> Tuple[Optional[float], Optional[float]]:
    if not gen["atr_risk"]:
        return None, None
    return candidate.get("stop_multiple_atr"), candidate.get("trail_multiple_atr")


def _search_generation(
    evaluator: _GenerationEvaluator,
    gen: Dict[str, Any],
    train_range: Tuple[int, int],
    validation_range: Tuple[int, int],
    rng: random.Random,
) -> Tuple[Dict[str, Any], float, float]:
    """训练段搜索 + 验证段复评。返回 (最佳候选, 最佳验证分, 参数稳健度)。"""
    train_start, train_end = train_range
    val_start, val_end = validation_range
    # A–D 只调经典键（保持 RNG 调用序列与改造前一致），E/F 调全部键
    scope = TUNABLE_SCOPES.get(gen["key"], ALL_TUNABLE_KEYS)

    def train_score(candidate: Dict[str, Any]) -> float:
        stop_atr, trail_atr = _candidate_risk(candidate, gen)
        _, score = evaluator.evaluate(
            candidate["thresholds"], train_start, train_end, gen, stop_atr, trail_atr,
        )
        return score

    candidates: List[Dict[str, Any]] = []
    default_candidate: Dict[str, Any] = {"thresholds": _default_tunable(scope)}
    if gen["atr_risk"]:
        default_candidate["stop_multiple_atr"] = 2.5
        default_candidate["trail_multiple_atr"] = 3.0
    candidates.append(default_candidate)
    for _ in range(SAMPLED_CANDIDATES):
        candidate: Dict[str, Any] = {"thresholds": _sample_tunable(rng, scope)}
        if gen["atr_risk"]:
            candidate["stop_multiple_atr"] = rng.choice(ATR_STOP_GRID)
            candidate["trail_multiple_atr"] = rng.choice(ATR_TRAIL_GRID)
        candidates.append(candidate)

    scored = [(train_score(c), index, c) for index, c in enumerate(candidates)]
    scored.sort(key=lambda item: (-item[0], item[1]))

    # 爬山：围绕训练段最优的少数候选做单步邻域搜索，
    # 避免对数十万级全网格组合做暴力枚举。
    pool: List[Tuple[float, int, Dict[str, Any]]] = list(scored[:HILL_CLIMB_SEEDS])
    for _, _, seed_candidate in scored[:HILL_CLIMB_SEEDS]:
        current: Dict[str, Any] = {
            "thresholds": dict(seed_candidate["thresholds"]),
            "stop_multiple_atr": seed_candidate.get("stop_multiple_atr"),
            "trail_multiple_atr": seed_candidate.get("trail_multiple_atr"),
        }
        current_score = train_score(current)
        for _ in range(HILL_CLIMB_SWEEPS):
            improved = False
            searches: List[Tuple[str, Sequence[float]]] = [
                (f"thresholds.{key}", TUNABLE_GRID[key]) for key in scope
            ]
            if gen["atr_risk"]:
                searches.append(("stop_multiple_atr", ATR_STOP_GRID))
                searches.append(("trail_multiple_atr", ATR_TRAIL_GRID))
            for path, grid in searches:
                if path.startswith("thresholds."):
                    key = path.split(".", 1)[1]
                    position = _grid_index(grid, current["thresholds"].get(key))
                else:
                    position = _grid_index(grid, current.get(path))
                for direction in (-1, 1):
                    new_position = position + direction
                    if not 0 <= new_position < len(grid):
                        continue
                    trial: Dict[str, Any] = {
                        "thresholds": dict(current["thresholds"]),
                        "stop_multiple_atr": current.get("stop_multiple_atr"),
                        "trail_multiple_atr": current.get("trail_multiple_atr"),
                    }
                    if path.startswith("thresholds."):
                        trial["thresholds"][key] = grid[new_position]
                    else:
                        trial[path] = grid[new_position]
                    trial_score = train_score(trial)
                    if trial_score > current_score + 1e-9:
                        current, current_score, improved = trial, trial_score, True
            if not improved:
                break
        pool.append((current_score, len(pool), current))

    # 只用训练段分数选出的 Top-K 进入验证段复评；测试段不参与任何选择。
    pool.sort(key=lambda item: (-item[0], item[1]))
    validated: List[Dict[str, Any]] = []
    for train_value, _, candidate in pool[:TOP_K]:
        stop_atr, trail_atr = _candidate_risk(candidate, gen)
        _, validation_score = evaluator.evaluate(
            candidate["thresholds"], val_start, val_end, gen, stop_atr, trail_atr,
        )
        validated.append({
            "candidate": candidate,
            "train_score": train_value,
            "validation_score": validation_score,
        })

    best = min(
        validated,
        key=lambda item: (
            -item["validation_score"],
            -item["train_score"],
            _param_distance(item["candidate"]["thresholds"], scope),
        ),
    )
    best_validation = best["validation_score"]
    plateau = sum(
        1 for item in validated
        if item["validation_score"] >= best_validation - EPS_SIMPLICITY
    )
    robustness = plateau / len(validated) if validated else 0.0
    return best["candidate"], best_validation, robustness


def _split_ranges(n: int, test_bars: Optional[int] = None) -> Dict[str, Tuple[int, int]]:
    """划分 训练/验证/测试 三段。

    - ``test_bars`` 为 None 时保持历史行为：训练 60% / 验证 20%，其余为测试。
    - 显式给出 ``test_bars`` 时，从尾部预留测试段（按需截断），剩余部分
      仍按 60:20 的相对比例切分训练与验证，验证段始终紧邻测试段。
    """
    usable = n - WARMUP_BARS
    if test_bars is None:
        train_len = int(usable * TRAIN_RATIO)
        validation_len = int(usable * VALIDATION_RATIO)
    else:
        max_test = min(int(usable * MAX_TEST_USABLE_RATIO), usable - MIN_TRAINVAL_BARS)
        test_len = max(0, min(int(test_bars), max_test))
        remaining = usable - test_len
        train_len = int(remaining * TRAIN_RATIO / (TRAIN_RATIO + VALIDATION_RATIO))
        validation_len = remaining - train_len
    train = (WARMUP_BARS, WARMUP_BARS + train_len - 1)
    validation = (WARMUP_BARS + train_len, WARMUP_BARS + train_len + validation_len - 1)
    test = (WARMUP_BARS + train_len + validation_len, n - 1)
    return {
        "train": train,
        "validation": validation,
        "test": test,
        "train_validation": (train[0], validation[1]),
    }


def _clip_train_range(
    ranges: Dict[str, Tuple[int, int]],
    dates: Sequence[str],
    train_start_date: Optional[str],
    train_end_date: Optional[str],
) -> Tuple[int, int]:
    """把用户选择的训练段日期范围裁剪到允许的训练区间内。"""
    lo, hi = ranges["train"]
    if not train_start_date and not train_end_date:
        return lo, hi
    start_idx = bisect_left(dates, train_start_date) if train_start_date else lo
    end_idx = bisect_right(dates, train_end_date) - 1 if train_end_date else hi
    start_idx = max(lo, min(start_idx, hi))
    end_idx = max(lo, min(end_idx, hi))
    if start_idx > end_idx:
        start_idx, end_idx = end_idx, start_idx
    if end_idx - start_idx + 1 < MIN_TRAIN_BARS:
        raise ValueError(
            f"训练段范围过小：至少需要 {MIN_TRAIN_BARS} 根日线，"
            f"当前仅 {end_idx - start_idx + 1} 根"
        )
    return start_idx, end_idx


def _equity_series(
    base: Dict[str, Any],
    simulation: Dict[str, Any],
    start_index: int,
    end_index: int,
) -> Optional[Dict[str, Any]]:
    """测试段累计收益序列：相对段首权益归一化为 0%，便于多策略同图对比。"""
    equity = simulation.get("equity") or []
    if not equity or equity[0] <= 0:
        return None
    values = [round((value / equity[0] - 1.0) * 100.0, 4) for value in equity]
    return {
        "dates": list(base["dates"][start_index:end_index + 1]),
        "values": values,
    }


def _map_window_to_dates(
    target_dates: Sequence[str],
    wanted_start: str,
    wanted_end: str,
) -> Optional[Tuple[int, int]]:
    """把主序列的日期窗口映射到目标序列（首个不早于起点 / 最后一个不晚于终点）。"""
    start = bisect_left(target_dates, wanted_start)
    end = bisect_right(target_dates, wanted_end) - 1
    if start >= len(target_dates) or end < start or start == end:
        return None
    return start, end


def _benchmark_entry(
    key: str,
    name_zh: str,
    name_en: str,
    description_zh: str,
    description_en: str,
    available: bool,
    segments: Dict[str, Optional[Dict[str, Any]]],
    test_equity: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "key": key,
        "name_zh": name_zh,
        "name_en": name_en,
        "description_zh": description_zh,
        "description_en": description_en,
        "available": available,
        "metrics": segments,
        "test_equity": test_equity,
    }


def _build_benchmarks(
    base: Dict[str, Any],
    ranges: Dict[str, Tuple[int, int]],
    evaluator: "_GenerationEvaluator",
    recommended_thresholds: Dict[str, Any],
    recommended_gen: Dict[str, Any],
    rec_stop: Optional[float],
    rec_trail: Optional[float],
    window_days: int,
    cost_pct_per_side: float,
    short_term_tax_pct: float,
    long_term_tax_pct: float,
    benchmark_bars: Optional[Sequence[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """构建三个基准，与策略在同一 训练+验证 / 测试 窗口对比：

    1. sp500_buy_hold：标普500 在窗口起点买入、终点卖出（仅一次往返）。
    2. stock_buy_hold：个股在窗口起点买入、终点卖出（仅一次往返）。
    3. strategy_on_sp500：沿用推荐策略在个股上的每笔买卖时点，
       改用标普500 价格成交，用于分离“择时信号”与“标的本身”的贡献。

    每个基准同时返回测试段累计收益序列（test_equity），供前端绘制
    与策略同图的累计收益曲线。
    """
    dates: List[str] = base["dates"]
    tv_start, tv_end = ranges["train_validation"]
    test_start, test_end = ranges["test"]
    empty_segments: Dict[str, Optional[Dict[str, Any]]] = {
        "train_validation": None, "test": None,
    }

    def segment_metrics(series: Dict[str, Any], bounds: Tuple[int, int]) -> Dict[str, Any]:
        simulation = simulate_buy_hold(series, bounds[0], bounds[1], cost_pct_per_side)
        return summarize_metrics(
            simulation, bounds[0], bounds[1],
            short_term_tax_pct=short_term_tax_pct,
            long_term_tax_pct=long_term_tax_pct,
        )

    def buy_hold_equity(
        series: Dict[str, Any], bounds: Tuple[int, int],
    ) -> Optional[Dict[str, Any]]:
        simulation = simulate_buy_hold(series, bounds[0], bounds[1], cost_pct_per_side)
        return _equity_series(series, simulation, bounds[0], bounds[1])

    benchmarks: List[Dict[str, Any]] = []

    # 标普500 序列准备（best-effort）
    sp_base: Optional[Dict[str, Any]] = None
    if benchmark_bars and len(benchmark_bars) >= MIN_BENCHMARK_BARS:
        try:
            sp_base = prepare_base_series(benchmark_bars)
        except (KeyError, TypeError, ValueError):
            sp_base = None
    sp_tv = (
        _map_window_to_dates(sp_base["dates"], dates[tv_start], dates[tv_end])
        if sp_base is not None else None
    )
    sp_test = (
        _map_window_to_dates(sp_base["dates"], dates[test_start], dates[test_end])
        if sp_base is not None else None
    )

    # 基准一：标普500 买入持有
    if sp_base is not None and sp_tv is not None:
        segments: Dict[str, Optional[Dict[str, Any]]] = {
            "train_validation": segment_metrics(sp_base, sp_tv),
            "test": segment_metrics(sp_base, sp_test) if sp_test is not None else None,
        }
        sp_test_equity = (
            buy_hold_equity(sp_base, sp_test) if sp_test is not None else None
        )
        benchmarks.append(_benchmark_entry(
            "sp500_buy_hold",
            "基准：标普500买入持有",
            "Benchmark: S&P 500 buy & hold",
            "在窗口起点开盘买入标普500、终点收盘卖出，仅一次往返。",
            "Buy the S&P 500 at window-start open and sell at window-end close; single round trip.",
            True,
            segments,
            test_equity=sp_test_equity,
        ))
    else:
        benchmarks.append(_benchmark_entry(
            "sp500_buy_hold",
            "基准：标普500买入持有",
            "Benchmark: S&P 500 buy & hold",
            "在窗口起点开盘买入标普500、终点收盘卖出，仅一次往返。",
            "Buy the S&P 500 at window-start open and sell at window-end close; single round trip.",
            False,
            dict(empty_segments),
        ))

    # 基准二：个股买入持有（始终可用）
    benchmarks.append(_benchmark_entry(
        "stock_buy_hold",
        "基准：个股买入持有",
        "Benchmark: stock buy & hold",
        "在窗口起点开盘买入该股票、终点收盘卖出，仅一次往返。",
        "Buy the stock at window-start open and sell at window-end close; single round trip.",
        True,
        {
            "train_validation": segment_metrics(base, (tv_start, tv_end)),
            "test": segment_metrics(base, (test_start, test_end)),
        },
        test_equity=buy_hold_equity(base, (test_start, test_end)),
    ))

    # 基准三：推荐策略买卖时点 × 标普500 价格
    unavailable_strategy_on_sp500 = _benchmark_entry(
        "strategy_on_sp500",
        "基准：推荐策略时点 × 标普500",
        "Benchmark: recommended signals on S&P 500",
        "沿用推荐策略在个股上的每笔买卖时点，改用标普500 价格成交。",
        "Replays every recommended-strategy entry/exit timing using S&P 500 prices.",
        False,
        dict(empty_segments),
    )
    if sp_base is None or sp_tv is None:
        benchmarks.append(unavailable_strategy_on_sp500)
        return benchmarks

    sim = simulate_trades(
        base,
        evaluator.signals(recommended_thresholds),
        tv_start,
        tv_end,
        window_days=window_days,
        cost_pct_per_side=cost_pct_per_side,
        use_trend_filter=recommended_gen["trend_filter"],
        use_volume_filter=recommended_gen["volume_filter"],
        stop_multiple_atr=rec_stop,
        trail_multiple_atr=rec_trail,
    )
    pairs = [(t["entry_date"], t["exit_date"]) for t in sim["trades"]]
    if not pairs:
        benchmarks.append(unavailable_strategy_on_sp500)
        return benchmarks

    def replay(pairs_subset: List[Tuple[str, str]], bounds: Tuple[int, int]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        signals = timing_signals_from_trades(sp_base, pairs_subset)
        # window_days=1：重放不重复施加间隔限制（原交易已满足）
        replayed = simulate_trades(
            sp_base, signals, bounds[0], bounds[1],
            window_days=1, cost_pct_per_side=cost_pct_per_side,
        )
        metrics = summarize_metrics(
            replayed, bounds[0], bounds[1],
            short_term_tax_pct=short_term_tax_pct,
            long_term_tax_pct=long_term_tax_pct,
        )
        return metrics, replayed

    tv_metrics, tv_sim = replay(pairs, sp_tv)
    segments = {"train_validation": tv_metrics, "test": None}
    test_equity = _equity_series(sp_base, tv_sim, sp_tv[0], sp_tv[1])
    if sp_test is not None:
        # 与策略测试段口径一致：推荐参数在个股测试段单独回测（段首空仓起步），
        # 再把该段买卖时点重放到标普500。旧实现从训练+验证段模拟里筛选
        # 测试段入场，但该模拟不会跨入测试段，导致测试段永远为空。
        test_sim_stock = simulate_trades(
            base,
            evaluator.signals(recommended_thresholds),
            test_start,
            test_end,
            window_days=window_days,
            cost_pct_per_side=cost_pct_per_side,
            use_trend_filter=recommended_gen["trend_filter"],
            use_volume_filter=recommended_gen["volume_filter"],
            stop_multiple_atr=rec_stop,
            trail_multiple_atr=rec_trail,
        )
        test_pairs = [(t["entry_date"], t["exit_date"]) for t in test_sim_stock["trades"]]
        if test_pairs:
            segments["test"], test_sim_sp = replay(test_pairs, sp_test)
            test_equity = _equity_series(sp_base, test_sim_sp, sp_test[0], sp_test[1])
    benchmarks.append(_benchmark_entry(
        "strategy_on_sp500",
        "基准：推荐策略时点 × 标普500",
        "Benchmark: recommended signals on S&P 500",
        "沿用推荐策略在个股上的每笔买卖时点，改用标普500 价格成交。",
        "Replays every recommended-strategy entry/exit timing using S&P 500 prices.",
        True,
        segments,
        test_equity=test_equity,
    ))
    return benchmarks


def run_auto_tune(
    bars: Sequence[Dict[str, Any]],
    window_days: int = 90,
    history_years: float = 10.0,
    cost_pct_per_side: float = DEFAULT_COST_PCT_PER_SIDE,
    seed: int = 20240501,
    benchmark_bars: Optional[Sequence[Dict[str, Any]]] = None,
    short_term_capital_gains_tax_pct: float = DEFAULT_SHORT_TERM_TAX_PCT,
    long_term_capital_gains_tax_pct: float = DEFAULT_LONG_TERM_TAX_PCT,
    test_years: float = 3.0,
    train_start_date: Optional[str] = None,
    train_end_date: Optional[str] = None,
    fine_tune_window_days: Optional[int] = None,
) -> Dict[str, Any]:
    """对单只股票执行 Auto Tune 并返回完整报告。

    工作流：历史数据 -> 训练段寻优 -> 验证段选择 -> 测试段样本外报告
    -> 按 “足够好中最简单” 推荐策略代际与参数（含复合 BUY/SELL 评分阈值）。

    策略代际 A–F：A 基线（默认阈值）、B +趋势过滤、C +ATR 风控、
    D 经典全参数 + 风控、E 多因子评分（BOLL/CCI/DMI/MFI/量能/52 周位置
    权重与触发水平寻优）、F 多因子 + 风控。A–D 只调经典参数（新因子
    权重恒 0，结果与改造前逐位一致），E/F 调全部参数。

    ``test_years`` 指定样本外测试段长度（年，从历史尾部预留）；训练/验证
    在剩余历史上仍按 60:20 相对比例划分。``train_start_date`` /
    ``train_end_date`` 可选，用于把训练段裁剪到用户选择的日期范围
    （验证段位置不受影响）。

    ``fine_tune_window_days`` 可选，启用 Fine Tune 滑动窗口扫描：在训练段
    内以该天数为窗口长度、窗口长度 1/5 为步长滑动，每个位置独立执行寻优，
    比较各样本外 CAGR，返回最优窗口位置及其参数。

    另附三个基准（与策略同窗口）：标普500 买入持有 / 个股买入持有 /
    推荐策略时点套用标普500。`benchmark_bars` 为标普500 日线（可选，
    缺失时对应基准标记为不可用）。

    税后指标按美国资本利得税近似：短期（持有不足一年）按普通所得边际
    税率、长期（持有满一年）按长期资本利得税率；默认取家庭应税收入
    约 40 万美元档（35% / 15%），仅用于展示对比，不构成税务建议。
    """
    total = len(bars)
    if total < MIN_TOTAL_BARS:
        raise ValueError(
            f"Auto Tune 需要至少 {MIN_TOTAL_BARS} 根日线数据，当前仅 {total} 根"
        )

    keep = int(history_years * TRADING_DAYS_PER_YEAR)
    if keep > 0 and total > keep:
        bars = bars[-keep:]

    base = prepare_base_series(bars)
    n = base["n"]
    dates: List[str] = base["dates"]
    ranges = _split_ranges(n, test_bars=round(test_years * TRADING_DAYS_PER_YEAR))
    train_bounds = _clip_train_range(ranges, dates, train_start_date, train_end_date)
    if train_bounds != ranges["train"]:
        ranges["train"] = train_bounds
        ranges["train_validation"] = (train_bounds[0], ranges["validation"][1])
    test_bars_used = ranges["test"][1] - ranges["test"][0] + 1

    def range_info(bounds: Tuple[int, int]) -> Dict[str, Any]:
        start, end = bounds
        return {
            "start_date": dates[start],
            "end_date": dates[end],
            "bars": end - start + 1,
        }

    rng = random.Random(seed)
    evaluator = _GenerationEvaluator(
        base, window_days, cost_pct_per_side,
        short_term_tax_pct=short_term_capital_gains_tax_pct,
        long_term_tax_pct=long_term_capital_gains_tax_pct,
    )

    strategies: List[Dict[str, Any]] = []
    validation_scores: Dict[str, float] = {}
    for gen in GENERATIONS:
        if gen["tuned"]:
            chosen, best_validation, robustness = _search_generation(
                evaluator, gen, ranges["train"], ranges["validation"], rng,
            )
        else:
            chosen = {"thresholds": _default_tunable(TUNABLE_SCOPES.get(gen["key"]))}
            _, best_validation = evaluator.evaluate(
                chosen["thresholds"], *ranges["validation"], gen,
            )
            robustness = None
        validation_scores[gen["key"]] = best_validation

        stop_atr, trail_atr = _candidate_risk(chosen, gen)
        metrics: Dict[str, Dict[str, Any]] = {}
        objectives: Dict[str, float] = {}
        for segment, bounds in ranges.items():
            segment_metrics, objective = evaluator.evaluate(
                chosen["thresholds"], bounds[0], bounds[1], gen, stop_atr, trail_atr,
            )
            metrics[segment] = segment_metrics
            objectives[segment] = round(objective, 4)

        test_bounds = ranges["test"]
        test_equity = _equity_series(
            base,
            evaluator.simulate(
                chosen["thresholds"], test_bounds[0], test_bounds[1],
                gen, stop_atr, trail_atr,
            ),
            test_bounds[0],
            test_bounds[1],
        )

        strategies.append({
            "key": gen["key"],
            "name_zh": gen["name_zh"],
            "name_en": gen["name_en"],
            "description_zh": gen["description_zh"],
            "description_en": gen["description_en"],
            "tuned": gen["tuned"],
            "params": {
                "thresholds": {
                    key: _coerce_param(
                        key, chosen["thresholds"].get(key, DEFAULT_THRESHOLDS[key]),
                    )
                    for key in CHART_THRESHOLD_KEYS
                },
                "stop_multiple_atr": stop_atr,
                "trail_multiple_atr": trail_atr,
            },
            "metrics": metrics,
            "objectives": objectives,
            "param_robustness": round(robustness, 4) if robustness is not None else None,
            "test_equity": test_equity,
        })

    best_key = max(validation_scores, key=lambda k: validation_scores[k])
    recommended_key = next(
        gen["key"] for gen in GENERATIONS
        if validation_scores[gen["key"]] >= validation_scores[best_key] - EPS_SIMPLICITY
    )
    if recommended_key == "A":
        reason_code = "baseline_sufficient"
    elif recommended_key == best_key:
        reason_code = "best_validation"
    else:
        reason_code = "simplicity_preference"

    recommended_gen = next(gen for gen in GENERATIONS if gen["key"] == recommended_key)
    recommended_entry = next(s for s in strategies if s["key"] == recommended_key)
    rec_stop = recommended_entry["params"]["stop_multiple_atr"]
    rec_trail = recommended_entry["params"]["trail_multiple_atr"]

    display_values: Dict[str, Any] = {
        **recommended_entry["params"]["thresholds"],
        "stop_multiple_atr": rec_stop,
        "trail_multiple_atr": rec_trail,
    }
    params_display: List[Dict[str, Any]] = []
    for key in PARAM_DISPLAY_ORDER:
        value = display_values.get(key)
        if value is None:
            continue
        params_display.append({
            "key": key,
            "value": value,
            "default": (
                _coerce_param(key, DEFAULT_THRESHOLDS[key])
                if key in DEFAULT_THRESHOLDS else None
            ),
        })

    benchmarks = _build_benchmarks(
        base=base,
        ranges=ranges,
        evaluator=evaluator,
        recommended_thresholds=recommended_entry["params"]["thresholds"],
        recommended_gen=recommended_gen,
        rec_stop=rec_stop,
        rec_trail=rec_trail,
        window_days=window_days,
        cost_pct_per_side=cost_pct_per_side,
        short_term_tax_pct=short_term_capital_gains_tax_pct,
        long_term_tax_pct=long_term_capital_gains_tax_pct,
        benchmark_bars=benchmark_bars,
    )

    # ------------------------------------------------------------------
    # Fine Tune: sliding window sweep over training data
    # ------------------------------------------------------------------
    fine_tune_result: Optional[Dict[str, Any]] = None
    if fine_tune_window_days and fine_tune_window_days > 0:
        train_lo, train_hi = ranges["train"]
        test_lo, test_hi = ranges["test"]
        total_train = train_hi - train_lo + 1
        window = min(fine_tune_window_days, total_train)
        if window >= MIN_TRAIN_BARS:
            step = max(1, window // 5)  # ~5 positions by default
            sweep_results: List[Dict[str, Any]] = []
            best_oos_cagr = -float("inf")
            best_sweep_idx = 0
            sweep_idx = 0
            pos = train_lo
            while pos + window - 1 <= train_hi:
                sweep_train = (pos, pos + window - 1)
                sweep_validation = (sweep_train[1] + 1, ranges["validation"][1])
                # Ensure validation is within bounds
                if sweep_validation[0] > ranges["validation"][1]:
                    sweep_validation = (sweep_train[1] + 1, min(sweep_train[1] + max(30, int(window * 0.2)), ranges["validation"][1]))
                if sweep_validation[0] > sweep_validation[1]:
                    pos += step
                    continue
                sweep_ranges: Dict[str, Tuple[int, int]] = {
                    "train": sweep_train,
                    "validation": sweep_validation,
                    "test": (test_lo, test_hi),
                    "train_validation": (sweep_train[0], sweep_validation[1]),
                }
                sweep_rng = random.Random(seed + sweep_idx)
                sweep_evaluator = _GenerationEvaluator(
                    base, window_days, cost_pct_per_side,
                    short_term_tax_pct=short_term_capital_gains_tax_pct,
                    long_term_tax_pct=long_term_capital_gains_tax_pct,
                )
                sweep_val_scores: Dict[str, float] = {}
                sweep_strategies: List[Dict[str, Any]] = []
                for gen in GENERATIONS:
                    if gen["tuned"]:
                        chosen, sv, rob = _search_generation(
                            sweep_evaluator, gen, sweep_ranges["train"],
                            sweep_ranges["validation"], sweep_rng,
                        )
                    else:
                        chosen = {"thresholds": _default_tunable(TUNABLE_SCOPES.get(gen["key"]))}
                        _, sv = sweep_evaluator.evaluate(
                            chosen["thresholds"], *sweep_ranges["validation"], gen,
                        )
                        rob = None
                    sweep_val_scores[gen["key"]] = sv
                    stop_a, trail_a = _candidate_risk(chosen, gen)
                    seg_metrics, seg_obj = sweep_evaluator.evaluate(
                        chosen["thresholds"], *sweep_ranges["test"], gen,
                        stop_a, trail_a,
                    )
                    sweep_strategies.append({
                        "key": gen["key"],
                        "name_zh": gen["name_zh"],
                        "name_en": gen["name_en"],
                        "tuned": gen["tuned"],
                        "test_cagr": seg_metrics.get("cagr_pct", 0.0),
                        "test_sharpe": seg_metrics.get("sharpe", 0.0),
                        "test_max_dd": seg_metrics.get("max_drawdown_pct", 0.0),
                        "test_trades": seg_metrics.get("trades", 0),
                        "validation_score": sv,
                        "thresholds": {
                            k: _coerce_param(
                                k, chosen["thresholds"].get(k, DEFAULT_THRESHOLDS[k]),
                            )
                            for k in CHART_THRESHOLD_KEYS
                        },
                        "stop_multiple_atr": stop_a,
                        "trail_multiple_atr": trail_a,
                    })
                # Pick best strategy for this window position by validation score
                sw_best_key = max(sweep_val_scores, key=lambda k: sweep_val_scores[k])
                sw_best = next(s for s in sweep_strategies if s["key"] == sw_best_key)
                sweep_results.append({
                    "position_index": sweep_idx,
                    "train_start": dates[sweep_train[0]],
                    "train_end": dates[sweep_train[1]],
                    "train_bars": window,
                    "validation_start": dates[sweep_validation[0]],
                    "validation_end": dates[sweep_validation[1]],
                    "best_strategy_key": sw_best_key,
                    "test_cagr": sw_best["test_cagr"],
                    "test_sharpe": sw_best["test_sharpe"],
                    "test_max_dd": sw_best["test_max_dd"],
                    "test_trades": sw_best["test_trades"],
                    "validation_score": sweep_val_scores[sw_best_key],
                    "thresholds": sw_best["thresholds"],
                    "stop_multiple_atr": sw_best["stop_multiple_atr"],
                    "trail_multiple_atr": sw_best["trail_multiple_atr"],
                    "all_strategies": sweep_strategies,
                })
                if sw_best["test_cagr"] > best_oos_cagr:
                    best_oos_cagr = sw_best["test_cagr"]
                    best_sweep_idx = sweep_idx
                sweep_idx += 1
                pos += step
            if sweep_results:
                fine_tune_result = {
                    "window_days": window,
                    "step": step,
                    "positions_tested": len(sweep_results),
                    "best_position_index": best_sweep_idx,
                    "sweep": sweep_results,
                }

    return {
        "window_days": window_days,
        "history": {
            "bars": n,
            "start_date": dates[0],
            "end_date": dates[-1],
            "years_requested": float(history_years),
            "years_used": round(n / TRADING_DAYS_PER_YEAR, 2),
            "test_years_requested": float(test_years),
            "test_years_used": round(test_bars_used / TRADING_DAYS_PER_YEAR, 2),
        },
        "split": {
            segment: range_info(ranges[segment])
            for segment in ("train", "validation", "test")
        },
        "assumptions": {
            "execution": "next_open",
            "cost_pct_per_side": cost_pct_per_side,
            "entry_gap_bars": window_days,
            "atr_period": 14,
            "trend_filter_ma": 200,
            "capital_gains_tax_short_term_pct": short_term_capital_gains_tax_pct,
            "capital_gains_tax_long_term_pct": long_term_capital_gains_tax_pct,
        },
        "fixed_parameters": {
            "keys": [
                "macd_fast", "macd_slow", "macd_signal",
                "kdj_period", "rsi_period", "rsi_smooth_fast", "rsi_smooth_slow",
            ],
            "reason_code": "indicator_periods_fixed",
        },
        "strategies": strategies,
        "benchmarks": benchmarks,
        "recommended": {
            "strategy_key": recommended_key,
            "reason_code": reason_code,
            "eps": EPS_SIMPLICITY,
            "thresholds": recommended_entry["params"]["thresholds"],
            "risk": {
                "use_trend_filter": recommended_gen["trend_filter"],
                "use_volume_filter": recommended_gen["volume_filter"],
                "stop_multiple_atr": rec_stop,
                "trail_multiple_atr": rec_trail,
            },
            "params_display": params_display,
        },
        "fine_tune": fine_tune_result,
    }
