# -*- coding: utf-8 -*-
"""
策略引擎（StrategyEngine）：买卖决策的唯一真源
=============================================

本模块是策略决策逻辑的唯一实现，被以下调用方共享：

1. 回测（``strategy_backtester.compute_composite_signals`` / ``simulate_trades``）
2. 实盘/图表信号（``indicator_service.compute_indicators`` 的复合评分段）
3. Auto Tune / Fine Tune 参数寻优（``indicator_optimizer``）
4. 未来的纸面/影子交易与信号服务（Phase 4+）

RSI/MACD 特征公式位于 indicator_service，评分公式位于 strategy_scoring；各调用方通过
``score_bar`` / ``signal_enter`` / ``evaluate_signals`` / ``evaluate``
复用同一份实现。

分层说明（与生产结构对应）：

- 特征层（Feature）：各调用方按自身性能需求准备指标序列
  （``prepare_base_series`` 调用 ``compute_indicators`` 共享特征公式，
  并按指标周期校验缓存）。
- 决策层（Strategy，本模块）：给定单根 bar 的特征与阈值，
  ``score_bar`` 输出确定性的买卖分数与因子分解，
  ``signal_enter`` 判定评分进入阈值区间的触发 bar。
- 执行层（Execution）：次日开盘成交、ATR 止损等仍由
  ``simulate_trades`` / ``execution_policy`` 建模，不属于本模块。

所有判断只使用截止当前 bar 的数据，无未来函数。
"""

from __future__ import annotations

from bisect import bisect_right, insort
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.services.composite_factors import (
    ExtraFactorScorer,
    compute_extra_factor_series,
)
from src.services.indicator_service import (
    DEFAULT_THRESHOLDS,
    MAX_BUY_SCORE,
    compute_indicators,
    _sma,
)
from src.services.strategy_scoring import (
    BarFeatures,
    score_bar,
    signal_enter,
)

# ---------------------------------------------------------------------------
# 策略代际定义（A–F）：决策开关的唯一真源
# ---------------------------------------------------------------------------
# A 基线（默认阈值，无额外过滤）；B +趋势过滤；C +ATR 风控；
# D 经典全参数 + 风控；E 多因子评分；F 多因子 + 风控。
# ``indicator_optimizer`` 从本模块导入（并重新导出以保持兼容）。

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


def generation_flags(strategy: str) -> Dict[str, bool]:
    """返回某代际的决策开关（trend_filter / volume_filter / atr_risk）。"""
    for gen in GENERATIONS:
        if gen["key"] == strategy:
            return {
                "trend_filter": bool(gen["trend_filter"]),
                "volume_filter": bool(gen["volume_filter"]),
                "atr_risk": bool(gen["atr_risk"]),
            }
    raise ValueError(f"未知的策略代际: {strategy!r}")


def resolve_thresholds(thresholds: Optional[Mapping[str, Any]] = None) -> Dict[str, float]:
    """合并默认阈值与用户覆盖（与历史行为一致：未知键忽略、非法值跳过）。"""
    th = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        for key, value in thresholds.items():
            if key in th and value is not None:
                try:
                    th[key] = float(value)
                except (TypeError, ValueError):
                    pass
    return th


def _feature_periods(thresholds):
    th = resolve_thresholds(thresholds)
    return tuple(th[key] for key in (
        "macd_fast", "macd_slow", "macd_signal", "kdj_period",
        "rsi_period", "rsi_smooth_fast", "rsi_smooth_slow",
    ))


def prepare_base_series(
    bars: Sequence[Dict[str, Any]], thresholds: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """共享图表指标公式；缓存只适用于相同的指标周期。"""
    n = len(bars)
    dates = [str(b.get("date", "")) for b in bars]
    close = [float(b["close"]) for b in bars]
    high = [float(b["high"]) for b in bars]
    low = [float(b["low"]) for b in bars]
    volume = [float(b.get("volume") or 0.0) for b in bars]

    features = compute_indicators(bars, thresholds)
    macd = features["macd"]
    macd_signal = features["macd_signal"]
    k_values, d_values = features["k"], features["d"]
    rsi, rsi6 = features["rsi"], features["rsi6"]

    # Wilder ATR(14)：前 14 根 TR 均值播种，之后递推平滑。
    atr: List[Optional[float]] = [None] * n
    trs: List[float] = []
    for i in range(n):
        if i == 0:
            trs.append(high[i] - low[i])
            continue
        trs.append(max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        ))
    prev_atr: Optional[float] = None
    for i in range(n):
        if i + 1 < 14:
            continue
        if prev_atr is None:
            prev_atr = sum(trs[: i + 1]) / 14.0
        else:
            prev_atr = (prev_atr * 13.0 + trs[i]) / 14.0
        atr[i] = prev_atr

    sma200 = _sma(close, 200)
    vol_sma20 = _sma(volume, 20)

    # 扩展因子序列（BOLL/CCI/DMI/MFI/量能/52 周位置），与 indicator_service 共享公式
    factor_series = compute_extra_factor_series(close, high, low, volume)

    return {
        "feature_periods": _feature_periods(thresholds),
        "bars": [dict(bar) for bar in bars],
        "n": n,
        "dates": dates,
        "open": [float(b["open"]) for b in bars],
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "macd": macd,
        "macd_signal": macd_signal,
        "k": k_values,
        "d": d_values,
        "rsi": rsi,
        "rsi6": rsi6,
        "atr": atr,
        "sma200": sma200,
        "vol_sma20": vol_sma20,
        "factor_series": factor_series,
    }


def evaluate_signals(
    base: Dict[str, Any],
    thresholds: Optional[Mapping[str, Any]] = None,
) -> Dict[str, List[Any]]:
    """在基础序列上计算复合评分与触发信号（回测/寻优共用）。

    MACD 滚动百分位用有序窗口实现（窗口仅含当前 bar 之前的数据且
    要求完整回看窗口，等价于逐窗百分位），复杂度 O(n log w)。
    返回分数、因子分解与触发信号（触发值为收盘价或 None）。
    """
    th = resolve_thresholds(thresholds)

    if base.get("feature_periods") != _feature_periods(th) and "bars" in base:
        base = prepare_base_series(base["bars"], th)

    n = base["n"]
    close: List[float] = base["close"]
    macd: List[float] = base["macd"]
    k_values: List[Optional[float]] = base["k"]
    d_values: List[Optional[float]] = base["d"]
    rsi: List[Optional[float]] = base["rsi"]
    rsi6: List[Optional[float]] = base["rsi6"]
    volume: List[float] = base.get("volume", [0.0] * n)
    # 扩展因子序列优先取 prepare_base_series 的共享结果；缺失时按同口径
    # 现场补算。
    factor_series = base.get("factor_series") or compute_extra_factor_series(
        base["close"], base["high"], base["low"], volume
    )
    extra_scorer = ExtraFactorScorer(factor_series, close, volume, th)

    lookback = max(2, int(th["macd_lookback"]))
    trend_period = max(2, int(th["trend_period"]))
    sma_trend = _sma(close, trend_period)
    buy_threshold = int(th["composite_buy_threshold"])
    sell_threshold = int(th["composite_sell_threshold"])
    kdj_low = th["kdj_low"]
    kdj_high = th["kdj_high"]
    rsi_os = th["rsi_low"]
    rs_ob = th["rsi_high"]
    macd_low_pct = th["macd_low_percentile"]
    macd_high_pct = th["macd_high_percentile"]
    momentum_period = max(1, int(th["momentum_period"]))
    momentum_min_change_pct = float(th["momentum_min_change_pct"])

    # 价格动量 ROC（%）及其环比变化；BUY/SELL 的方向确认在 score_bar 内完成。
    momentum_pct: List[Optional[float]] = [None] * n
    for i in range(momentum_period, n):
        prev_close = close[i - momentum_period]
        if prev_close == 0:
            continue
        momentum_pct[i] = (close[i] - prev_close) / prev_close * 100.0

    momentum_delta: List[Optional[float]] = [None] * n
    for i in range(1, n):
        if momentum_pct[i] is None or momentum_pct[i - 1] is None:
            continue
        momentum_delta[i] = momentum_pct[i] - momentum_pct[i - 1]  # type: ignore[operator]

    # 将阈值子集打包为 score_bar 的输入视图（键名与公式引用保持一致）。
    score_th = {
        "macd_low_percentile": macd_low_pct,
        "macd_high_percentile": macd_high_pct,
        "kdj_low": kdj_low,
        "kdj_high": kdj_high,
        "rsi_low": rsi_os,
        "rsi_high": rs_ob,
        "momentum_min_change_pct": momentum_min_change_pct,
    }

    buy_score: List[int] = [0] * n
    sell_score: List[int] = [0] * n
    buy_breakdown: List[Dict[str, int]] = [{} for _ in range(n)]
    sell_breakdown: List[Dict[str, int]] = [{} for _ in range(n)]
    buy_signal: List[Optional[float]] = [None] * n
    sell_signal: List[Optional[float]] = [None] * n

    # 有序窗口维护 MACD 滚动百分位（窗口仅含当前 bar 之前的数据，
    # 等价于 count(v <= current) / len(prior_window) * 100）。
    window_sorted: List[float] = []

    for i in range(n):
        # 先用“当前 bar 之前”的完整窗口计算百分位，再插入当前值并淘汰过期值
        # （len(window_sorted) == lookback 等价于 i >= lookback）
        macd_pct = (
            bisect_right(window_sorted, macd[i]) * 100.0 / len(window_sorted)
            if len(window_sorted) >= lookback
            else None
        )
        insort(window_sorted, macd[i])
        if len(window_sorted) > lookback:
            expired = macd[i - lookback]
            del window_sorted[bisect_right(window_sorted, expired) - 1]

        extra_buy, extra_sell, extra_bd, extra_sd = extra_scorer.score_at(i)
        scored = score_bar(
            BarFeatures(
                macd_pct=macd_pct,
                macd_rising=i >= 1 and macd[i] > macd[i - 1],
                macd_declining=i >= 1 and macd[i] < macd[i - 1],
                k=k_values[i],
                d=d_values[i],
                k_prev=k_values[i - 1] if i >= 1 else None,
                d_prev=d_values[i - 1] if i >= 1 else None,
                rsi=rsi[i],
                rsi6=rsi6[i],
                rsi6_prev=rsi6[i - 1] if i >= 1 else None,
                close=close[i],
                close_prev=close[i - 1] if i >= 1 else None,
                sma_trend=sma_trend[i],
                sma_trend_prev=sma_trend[i - 1] if i >= 1 else None,
                momentum_delta=momentum_delta[i],
                extra_buy=extra_buy,
                extra_sell=extra_sell,
                extra_buy_breakdown=extra_bd,
                extra_sell_breakdown=extra_sd,
            ),
            score_th,
        )

        buy_score[i] = scored.buy
        sell_score[i] = scored.sell
        buy_breakdown[i] = scored.buy_breakdown
        sell_breakdown[i] = scored.sell_breakdown

        prev_buy = buy_score[i - 1] if i > 0 else 0
        prev_sell = sell_score[i - 1] if i > 0 else 0
        buy_enter, sell_enter = signal_enter(
            prev_buy, scored.buy, prev_sell, scored.sell,
            buy_threshold, sell_threshold,
        )
        if buy_enter:
            buy_signal[i] = close[i]
        elif sell_enter:
            sell_signal[i] = close[i]

    maximum_buy_score = MAX_BUY_SCORE + extra_scorer.max_extra()
    return {
        "buy_score": buy_score,
        "buy_allocation": [max(0.25, min(1.0, score / maximum_buy_score)) for score in buy_score],
        "sell_score": sell_score,
        "buy_breakdown": buy_breakdown,
        "sell_breakdown": sell_breakdown,
        "buy_signal": buy_signal,
        "sell_signal": sell_signal,
    }


@dataclass(frozen=True)
class StrategyDecision:
    """单根 bar 的策略决策（可解释、不绑定券商/订单逻辑）。"""

    date: str
    index: int
    action: str  # "BUY" / "SELL" / "HOLD"
    buy_score: int
    sell_score: int
    buy_threshold: int
    sell_threshold: int
    close: float
    factors: Dict[str, int]
    buy_breakdown: Dict[str, int]
    sell_breakdown: Dict[str, int]
    filters: Dict[str, Any]


def evaluate(
    bars: Sequence[Dict[str, Any]],
    strategy: str = "A",
    parameters: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """对历史 finalized OHLCV 运行指定代际策略，返回逐 bar 确定性决策。

    Args:
        bars: 升序 K 线列表（date/open/high/low/close/volume）。
        strategy: 代际键（A–F），决定趋势/成交量过滤等决策开关。
        parameters: 阈值覆盖（键见 DEFAULT_THRESHOLDS；未知键忽略）。

    决策语义（与回测/图表一致）：
    - action 取自评分进入阈值区间的触发信号；
    - 代际的趋势/成交量过滤只作用于 BUY（与 simulate_trades 的入场门控一致），
      门控状态如实记录在 ``filters`` 中；
    - SELL 不受过滤门控（与回测一致）。
    """
    flags = generation_flags(strategy)
    th = resolve_thresholds(parameters)
    base = prepare_base_series(bars, th)
    signals = evaluate_signals(base, th)

    n = base["n"]
    dates: List[str] = base["dates"]
    close: List[float] = base["close"]
    volume: List[float] = base["volume"]
    sma200: List[Optional[float]] = base["sma200"]
    vol_sma20: List[Optional[float]] = base["vol_sma20"]
    buy_threshold = int(th["composite_buy_threshold"])
    sell_threshold = int(th["composite_sell_threshold"])

    decisions: List[StrategyDecision] = []
    for i in range(n):
        # 趋势门控（与 simulate_trades 入场过滤同规则）：
        # Close > SMA200 且 SMA200 上行；任一缺失即不通过。
        if i >= 1 and sma200[i] is not None and sma200[i - 1] is not None:
            trend_gate = bool(close[i] > sma200[i] and sma200[i] > sma200[i - 1])  # type: ignore[operator]
        else:
            trend_gate = False
        # 成交量门控（同规则）：当日量 > 20 日均量。
        vol_ref = vol_sma20[i]
        volume_gate = bool(vol_ref is not None and volume[i] > vol_ref)

        buy_fired = signals["buy_signal"][i] is not None
        sell_fired = signals["sell_signal"][i] is not None
        if sell_fired:
            action = "SELL"
        elif buy_fired and (not flags["trend_filter"] or trend_gate) and (
            not flags["volume_filter"] or volume_gate
        ):
            action = "BUY"
        else:
            action = "HOLD"
        buy_bd = signals["buy_breakdown"][i]
        sell_bd = signals["sell_breakdown"][i]
        decisions.append(StrategyDecision(
            date=dates[i],
            index=i,
            action=action,
            buy_score=signals["buy_score"][i],
            sell_score=signals["sell_score"][i],
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            close=close[i],
            factors=dict(buy_bd) if action != "SELL" else dict(sell_bd),
            buy_breakdown=dict(buy_bd),
            sell_breakdown=dict(sell_bd),
            filters={
                "trend_filter": flags["trend_filter"],
                "volume_filter": flags["volume_filter"],
                "trend_gate": trend_gate,
                "volume_gate": volume_gate,
            },
        ))

    return {
        "strategy": strategy,
        "thresholds": th,
        "dates": dates,
        "decisions": decisions,
    }
