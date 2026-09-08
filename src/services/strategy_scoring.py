# -*- coding: utf-8 -*-
"""
策略打分公式（Strategy Scoring）：买卖评分的唯一实现
====================================================

本模块只包含无状态的纯函数，不依赖任何业务模块，
因此可被 ``strategy_engine``、``indicator_service``、
``strategy_backtester`` 同时导入而不产生循环依赖。

经典因子满分 10（MACD/KDJ/RSI/动量各 2 分 + 趋势 regime 2 分，
BUY/SELL 对称）；扩展因子（BOLL/CCI/DMI/MFI/量能/52 周位置）
按各自权重在经典分之上加分。所有判断只使用截止当前 bar 的
数据，无未来函数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple

from src.services.composite_factors import FACTOR_BREAKDOWN_KEYS


@dataclass(frozen=True)
class BarFeatures:
    """单根 bar 的决策输入（全部使用截止当前 bar 的数据）。"""

    macd_pct: Optional[float]
    macd_rising: bool = False
    macd_declining: bool = False
    k: Optional[float] = None
    d: Optional[float] = None
    k_prev: Optional[float] = None
    d_prev: Optional[float] = None
    rsi: Optional[float] = None
    rsi6: Optional[float] = None
    rsi6_prev: Optional[float] = None
    close: float = 0.0
    close_prev: Optional[float] = None
    sma_trend: Optional[float] = None
    sma_trend_prev: Optional[float] = None
    momentum_delta: Optional[float] = None
    extra_buy: int = 0
    extra_sell: int = 0
    extra_buy_breakdown: Mapping[str, int] = field(default_factory=dict)
    extra_sell_breakdown: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoredBar:
    """单根 bar 的评分结果（含因子分解，供图表与信号解释复用）。"""

    buy: int
    sell: int
    buy_breakdown: Dict[str, int]
    sell_breakdown: Dict[str, int]


def _zero_breakdown() -> Dict[str, int]:
    return {
        "macd": 0, "kdj": 0, "rsi": 0, "regime": 0, "momentum": 0,
        **{key: 0 for key in FACTOR_BREAKDOWN_KEYS},
    }


def score_bar(feat: BarFeatures, th: Mapping[str, float]) -> ScoredBar:
    """复合 BUY/SELL 评分公式的唯一实现。"""
    bd = _zero_breakdown()
    sd = _zero_breakdown()
    b = 0
    s = 0

    # 深跌低位 + 向上反转 / 高位 + 向下反转
    if (
        feat.macd_pct is not None
        and feat.macd_pct <= th["macd_low_percentile"]
        and feat.macd_rising
    ):
        bd["macd"] = 2
        b += 2
    if (
        feat.macd_pct is not None
        and feat.macd_pct >= th["macd_high_percentile"]
        and feat.macd_declining
    ):
        sd["macd"] = 2
        s += 2

    # KDJ 超卖金叉 / 超买死叉
    if None not in (feat.k, feat.d, feat.k_prev, feat.d_prev):
        golden_cross = (
            feat.k > feat.d  # type: ignore[operator]
            and feat.k_prev <= feat.d_prev  # type: ignore[operator]
        )
        death_cross = (
            feat.k < feat.d  # type: ignore[operator]
            and feat.k_prev >= feat.d_prev  # type: ignore[operator]
        )
        if (
            feat.k < th["kdj_low"]  # type: ignore[operator]
            and feat.d < th["kdj_low"]  # type: ignore[operator]
            and golden_cross
        ):
            bd["kdj"] = 2
            b += 2
        if (
            feat.k > th["kdj_high"]  # type: ignore[operator]
            and feat.d > th["kdj_high"]  # type: ignore[operator]
            and death_cross
        ):
            sd["kdj"] = 2
            s += 2

    # RSI 极端 + 反转（快速平滑 RSI 转向）
    if None not in (feat.rsi, feat.rsi6, feat.rsi6_prev):
        if feat.rsi < th["rsi_low"] and feat.rsi6 > feat.rsi6_prev:  # type: ignore[operator]
            bd["rsi"] = 2
            b += 2
        if feat.rsi > th["rsi_high"] and feat.rsi6 < feat.rsi6_prev:  # type: ignore[operator]
            sd["rsi"] = 2
            s += 2

    # 长期趋势 regime：价格相对趋势均线 + 均线方向（各 0-1 分，BUY/SELL 对称）
    if feat.sma_trend is not None:
        if feat.close > feat.sma_trend:
            bd["regime"] += 1
            b += 1
        elif feat.close < feat.sma_trend:
            sd["regime"] += 1
            s += 1

        if feat.sma_trend_prev is not None:
            if feat.sma_trend > feat.sma_trend_prev:
                bd["regime"] += 1
                b += 1
            elif feat.sma_trend < feat.sma_trend_prev:
                sd["regime"] += 1
                s += 1

    # 动量改善 / 恶化：BUY 要求 ROC 改善且当日上涨；
    # SELL 要求 ROC 恶化且当下跌（避免弱反弹误加分）。
    delta = feat.momentum_delta
    if delta is not None and feat.close_prev is not None:
        if (
            delta > th["momentum_min_change_pct"]
            and feat.close > feat.close_prev
        ):
            bd["momentum"] = 2
            b += 2
        elif (
            delta < -th["momentum_min_change_pct"]
            and feat.close < feat.close_prev
        ):
            sd["momentum"] = 2
            s += 2

    # 扩展因子（BOLL/CCI/DMI/MFI/量能/52 周位置）：权重 0 时零贡献
    b += feat.extra_buy
    s += feat.extra_sell
    bd.update(feat.extra_buy_breakdown)
    sd.update(feat.extra_sell_breakdown)

    return ScoredBar(buy=b, sell=s, buy_breakdown=bd, sell_breakdown=sd)


def signal_enter(
    prev_buy: int,
    buy: int,
    prev_sell: int,
    sell: int,
    buy_threshold: int,
    sell_threshold: int,
) -> Tuple[bool, bool]:
    """评分“进入”阈值区间的触发判定（与图表标记语义一致）。

    信号仅在评分进入阈值区间的那根 bar 触发；同一根 bar 买卖同时
    进入区间时视为方向不明，不产生任何标记。
    """
    buy_enter = buy >= buy_threshold and prev_buy < buy_threshold
    sell_enter = sell >= sell_threshold and prev_sell < sell_threshold
    if buy_enter and sell_enter:
        return False, False
    return buy_enter, sell_enter
