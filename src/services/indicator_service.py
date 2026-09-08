# -*- coding: utf-8 -*-
"""
===================================
技术指标计算（Excel "300 Plot" 逻辑）
===================================

复刻 Single.xlsx 中 "300 Plot" 工作表的指标计算公式。
数据列约定（与 Excel 一致）：
    date / open / high / low / close / volume

所有函数接收按时间升序排列的 K 线字典列表，返回与输入等长的
指标序列（前置不足窗口的位置为 None）。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from src.services.composite_factors import (
    ExtraFactorScorer,
    compute_extra_factor_series,
    compute_extra_triggers,
)
from src.services.strategy_scoring import (
    BarFeatures,
    score_bar,
    signal_enter,
)

# Excel "Today" 工作表第 52 行的默认阈值
DEFAULT_THRESHOLDS: Dict[str, float] = {
    "bol_constant": 0.1,   # F52 BOL constant
    "macd_buy": 0.7,       # G52 MACD Buy
    "macd_sell": 0.99,     # H52 MACD Sell
    "kdj_buy": 40.0,       # I52 KDJ Buy
    "kdj_sell": 70.0,      # J52 KDJ Sell
    "rsi_buy": 10.0,       # K52 RSI Buy
    "rsi_sell": 70.0,      # L52 RSI Sell
    # 复合 BUY/SELL 评分阈值（归一化，不依赖绝对价格量级）
    "composite_buy_threshold": 6.0,   # BUY 评分触发阈值（满分 10）
    "composite_sell_threshold": 6.0,  # SELL 评分触发阈值（满分 10）
    "macd_lookback": 120.0,           # MACD 百分位回看窗口（根，不含当前 bar）
    "macd_low_percentile": 15.0,      # MACD 低位百分位阈值（%）
    "macd_high_percentile": 85.0,     # MACD 高位百分位阈值（%）
    "rsi_low": 15.0,                  # RSI 超卖阈值
    "rsi_high": 85.0,                 # RSI 超买阈值
    "kdj_low": 40.0,                  # KDJ 超卖阈值（K、D 同时低于该值）
    "kdj_high": 70.0,                 # KDJ 超买阈值（K、D 同时高于该值）
    "trend_period": 200.0,            # 长期趋势均线周期（regime 分）
    "momentum_period": 5.0,           # 价格动量回看周期（根）
    "momentum_min_change_pct": 0.25,  # 动量改善/恶化的最小变化阈值（%），并要求当日价格同向确认
    # 指标周期参数（默认与经典设置一致；供微调使用）
    "macd_fast": 12.0,                # MACD 快线 EMA 周期
    "macd_slow": 26.0,                # MACD 慢线 EMA 周期
    "macd_signal": 9.0,               # MACD 信号线 EMA 周期
    "kdj_period": 9.0,                # KDJ RSV 窗口周期
    "rsi_period": 14.0,               # RSI 计算周期
    "rsi_smooth_fast": 6.0,           # RSI 快速平滑周期（RSI6）
    "rsi_smooth_slow": 14.0,          # RSI 慢速平滑周期（RSI14）
    # 扩展因子（BOLL/CCI/DMI/MFI/量能/52 周位置）：
    # 触发水平 + 权重（整数点数），权重 0 = 不参与复合评分（保持旧代际行为）
    "boll_buy_level": 0.1,            # BOLL %B 向上穿越的看多水平
    "boll_sell_level": 0.9,           # BOLL %B 向下穿越的看空水平
    "boll_weight": 0.0,               # BOLL %B 因子分数权重
    "cci_buy_level": -100.0,          # CCI 向上穿越的看多水平
    "cci_sell_level": 100.0,          # CCI 向下穿越的看空水平
    "cci_weight": 0.0,                # CCI 因子分数权重
    "adx_min_level": 20.0,            # DMI 触发要求的 ADX 趋势强度下限
    "dmi_weight": 0.0,                # DMI 因子分数权重
    "mfi_buy_level": 20.0,            # MFI 向上穿越的看多水平
    "mfi_sell_level": 80.0,           # MFI 向下穿越的看空水平
    "mfi_weight": 0.0,                # MFI 因子分数权重
    "volume_confirm_level": 1.5,      # 量能确认：volume/SMA20(volume) 下限
    "volume_weight": 0.0,             # 量能确认因子分数权重
    "range52_high_level": 0.95,       # 52 周位置：close/252 日最高 的看多水平
    "range52_low_level": 1.05,        # 52 周位置：close/252 日最低 的看空水平
    "range52_weight": 0.0,            # 52 周位置因子分数权重
}

SMA_PERIODS = [5, 9, 10, 12, 20, 26, 30, 40, 50, 60, 120, 200]
EMA_PERIODS = [5, 9, 12, 20, 26, 40, 60, 120, 200]
OBV_PERIODS = [5, 10, 20, 40, 60]

# 经典复合评分满分：MACD/KDJ/RSI/动量各 2 分 + 趋势 regime 2 分。
# 扩展因子（BOLL/CCI/DMI/MFI/量能/52 周位置）在经典分之上按权重加分，
# 最终满分 = 经典满分 + 启用扩展因子权重和（默认权重 0 → 满分仍为 10）。
MAX_BUY_SCORE = 10
MAX_SELL_SCORE = 10


def _closes(bars: Sequence[Dict[str, Any]]) -> List[float]:
    return [float(b["close"]) for b in bars]


def _sma(values: Sequence[float], period: int) -> List[Optional[float]]:
    """SMA{n} = AVERAGE of last n values（前置不足为 None）。"""
    out: List[Optional[float]] = []
    for i in range(len(values)):
        if i + 1 < period:
            out.append(None)
        else:
            window = values[i + 1 - period: i + 1]
            out.append(sum(window) / period)
    return out


def _ema(values: Sequence[float], period: int) -> List[Optional[float]]:
    """EMA{n} = v*2/(1+n) + prev*(1-2/(1+n))，首个值用首个收盘价种子。"""
    k = 2.0 / (1 + period)
    out: List[Optional[float]] = []
    prev: Optional[float] = None
    for v in values:
        if prev is None:
            prev = v
        else:
            prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def _rolling_min(values: Sequence[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for i in range(len(values)):
        if i + 1 < period:
            out.append(None)
        else:
            out.append(min(values[i + 1 - period: i + 1]))
    return out


def _rolling_max(values: Sequence[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for i in range(len(values)):
        if i + 1 < period:
            out.append(None)
        else:
            out.append(max(values[i + 1 - period: i + 1]))
    return out


def _percentile_rank(values: Sequence[float], current: float) -> Optional[float]:
    """`current` 在 `values` 中的百分位（0-100），用于归一化比较。

    与全历史极值不同，这里只依赖传入的滚动窗口，因此对不同价格量级的
    股票都适用。窗口为空时返回 None（调用方跳过该 bar 的评分）。
    """
    if not values:
        return None
    count = sum(1 for v in values if v <= current)
    return count * 100.0 / len(values)


def compute_indicators(
    bars: Sequence[Dict[str, Any]],
    thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    按 Excel "300 Plot" 逻辑计算全部指标。

    Args:
        bars: 升序 K 线列表，每项含 date/open/high/low/close/volume。
        thresholds: 可选阈值覆盖，键见 DEFAULT_THRESHOLDS。

    Returns:
        {
            "dates": [...],
            "close": [...],
            "sma": {"5": [...], ...},
            "ema": {"5": [...], ...},
            "macd": [...], "macd_signal": [...],
            "k": [...], "d": [...], "j": [...],
            "rsi": [...], "rsi6": [...], "rsi14": [...],
            "bolu": [...], "bold": [...],
            "cci": [...],
            "obv": [...], "obv_ma": {"5": [...], ...},
            "triggers": {
                "macd_buy": [...], "macd_sell": [...],
                "kdj_buy": [...], "kdj_sell": [...],
                "rsi_buy": [...], "rsi_sell": [...],
                "obv_buy": [...], "obv_sell": [...],
                "boll_buy": [...], "boll_sell": [...],
                "cci_buy": [...], "cci_sell": [...],
                "dmi_buy": [...], "dmi_sell": [...],
                "mfi_buy": [...], "mfi_sell": [...],
            },
            "composite": {
                "buy_score": [...], "sell_score": [...],
                "buy_signal": [...], "sell_signal": [...],
                "buy_breakdown": [{"macd":..,"kdj":..,"rsi":..,"regime":..,"momentum":..,
                                   "boll":..,"cci":..,"dmi":..,"mfi":..,"volume":..,"range52":..}, ...],
                "sell_breakdown": [...],
                "max_buy_score": 10 + 启用扩展因子权重和, "max_sell_score": 同上,
            },
        }
        所有序列与输入等长，触发器序列为收盘价或 None。
        复合评分为归一化 BUY/SELL 评分（经典因子满分均为 10：
        MACD/KDJ/RSI/动量各 2 分 + 趋势 regime 2 分），
        扩展因子（BOLL %B / CCI / DMI / MFI / 量能 / 52 周位置）按各自
        权重（默认 0，即禁用）在经典分基础上加分，满分随之动态变化；
        动量因子衡量 ROC 环比改善/恶化而非绝对涨跌，
        且要求当日收盘价同向确认（改善且上涨才计 BUY 分，
        恶化且下跌才计 SELL 分）；
        MACD 百分位要求完整回看窗口；
        信号仅在评分“进入”阈值区间的那根 bar 触发，
        同一根 bar 买卖同时进入区间时不产生标记；无未来函数。
    """
    th = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        for key, value in thresholds.items():
            if key in th and value is not None:
                try:
                    th[key] = float(value)
                except (TypeError, ValueError):
                    pass

    n = len(bars)
    dates = [str(b.get("date", "")) for b in bars]
    close = _closes(bars)
    high = [float(b["high"]) for b in bars]
    low = [float(b["low"]) for b in bars]
    volume = [float(b.get("volume") or 0.0) for b in bars]

    # Typical Price = (High + Low + Close) / 3
    typical = [(high[i] + low[i] + close[i]) / 3.0 for i in range(n)]

    # SMA / EMA
    sma = {str(p): _sma(close, p) for p in SMA_PERIODS}
    ema = {str(p): _ema(close, p) for p in EMA_PERIODS}

    # MACD = EMA(fast) - EMA(slow); Signal = EMA(signal)(MACD)
    macd_fast = max(1, int(th["macd_fast"]))
    macd_slow = max(macd_fast + 1, int(th["macd_slow"]))
    ema_fast = _ema(close, macd_fast)
    ema_slow = _ema(close, macd_slow)
    macd: List[float] = [
        (ema_fast[i] or 0.0) - (ema_slow[i] or 0.0) for i in range(n)
    ]
    macd_signal = _ema(macd, max(1, int(th["macd_signal"])))

    # MACD triggers
    macd_buy: List[Optional[float]] = [None] * n
    macd_sell: List[Optional[float]] = [None] * n
    for i in range(n):
        # Buy: MACD<0 AND MACD< buy*MIN(MACD[..i-1]) AND MACD>MIN(MACD[..i-1])
        if i >= 1 and macd[i] < 0:
            prior = macd[:i]
            min_prior = min(prior)
            if min_prior < macd[i] < th["macd_buy"] * min_prior:
                macd_buy[i] = close[i]
        # Sell: MACD>0 AND AVG(MACD[i-2..i])> sell*MAX(MACD[i-30..i-1]) AND AVG<MAX
        if i >= 3 and macd[i] > 0:
            avg3 = sum(macd[i - 2: i + 1]) / 3.0
            prior_window = macd[max(0, i - 30): i]
            if prior_window:
                max_prior = max(prior_window)
                if th["macd_sell"] * max_prior < avg3 < max_prior:
                    macd_sell[i] = close[i]

    # RSV = (Close - MIN(Low,N)) / (MAX(High,N) - MIN(Low,N)) * 100
    kdj_period = max(2, int(th["kdj_period"]))
    low_min_n = _rolling_min(low, kdj_period)
    high_max_n = _rolling_max(high, kdj_period)
    rsv: List[Optional[float]] = [None] * n
    for i in range(n):
        if low_min_n[i] is not None and high_max_n[i] is not None:
            denom = high_max_n[i] - low_min_n[i]  # type: ignore[operator]
            rsv[i] = 50.0 if denom == 0 else (close[i] - low_min_n[i]) / denom * 100.0  # type: ignore[operator]

    # K = RSV/3 + Kprev*2/3 ; D = K/3 + Dprev*2/3 ; J = 3K - 2D
    k_values: List[Optional[float]] = [None] * n
    d_values: List[Optional[float]] = [None] * n
    j_values: List[Optional[float]] = [None] * n
    k_prev = 50.0
    d_prev = 50.0
    for i in range(n):
        if rsv[i] is None:
            k_values[i] = None
            d_values[i] = None
            j_values[i] = None
            continue
        k_cur = rsv[i] / 3.0 + k_prev * 2.0 / 3.0  # type: ignore[operator]
        d_cur = k_cur / 3.0 + d_prev * 2.0 / 3.0
        j_cur = 3.0 * k_cur - 2.0 * d_cur
        k_values[i] = k_cur
        d_values[i] = d_cur
        j_values[i] = j_cur
        k_prev = k_cur
        d_prev = d_cur

    # KDJ triggers（触发时取前一日收盘价，与 Excel 一致）
    kdj_buy: List[Optional[float]] = [None] * n
    kdj_sell: List[Optional[float]] = [None] * n
    for i in range(1, n):
        if None in (k_values[i], d_values[i], k_values[i - 1], d_values[i - 1]):
            continue
        if (
            k_values[i] < th["kdj_buy"]  # type: ignore[operator]
            and d_values[i] < th["kdj_buy"]  # type: ignore[operator]
            and k_values[i] > d_values[i]  # type: ignore[operator]
            and k_values[i - 1] < d_values[i - 1]  # type: ignore[operator]
        ):
            kdj_buy[i] = close[i - 1]
        if (
            k_values[i] > th["kdj_sell"]  # type: ignore[operator]
            and d_values[i] > th["kdj_sell"]  # type: ignore[operator]
            and k_values[i] < d_values[i]  # type: ignore[operator]
            and k_values[i - 1] > d_values[i - 1]  # type: ignore[operator]
        ):
            kdj_sell[i] = close[i - 1]

    # RSI：%Gain/%Loss -> RS -> RSI(30~70) -> RSI 快/慢平滑
    rsi_period = max(2, int(th["rsi_period"]))
    gains: List[float] = [0.0] * n
    losses: List[float] = [0.0] * n
    for i in range(1, n):
        if close[i] > close[i - 1]:
            gains[i] = (close[i] - close[i - 1]) / close[i - 1]
        elif close[i] < close[i - 1]:
            losses[i] = (close[i - 1] - close[i]) / close[i - 1]

    rsi: List[Optional[float]] = [None] * n
    for i in range(n):
        if i < rsi_period:
            rsi[i] = None
            continue
        sum_gain = sum(gains[i - rsi_period: i])      # SUM(AP[r-N..r-1])
        sum_loss = sum(losses[i - rsi_period: i])
        avg_gain = (sum_gain / rsi_period * (rsi_period - 1.0) + gains[i]) / rsi_period
        avg_loss = (sum_loss / rsi_period * (rsi_period - 1.0) + losses[i]) / rsi_period
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - 100.0 / (1.0 + rs)

    def _avg_opt(values: Sequence[Optional[float]], period: int) -> List[Optional[float]]:
        out: List[Optional[float]] = []
        for i in range(len(values)):
            if i + 1 < period:
                out.append(None)
                continue
            window = values[i + 1 - period: i + 1]
            if any(v is None for v in window):
                out.append(None)
            else:
                out.append(sum(v for v in window if v is not None) / period)
        return out

    rsi6 = _avg_opt(rsi, max(1, int(th["rsi_smooth_fast"])))
    rsi14 = _avg_opt(rsi, max(1, int(th["rsi_smooth_slow"])))

    rsi_buy: List[Optional[float]] = [None] * n
    rsi_sell: List[Optional[float]] = [None] * n
    for i in range(1, n):
        if None in (rsi[i], rsi6[i], rsi14[i], rsi6[i - 1], rsi14[i - 1]):
            continue
        if (
            rsi[i] < th["rsi_buy"]  # type: ignore[operator]
            and rsi6[i] > rsi14[i]  # type: ignore[operator]
            and rsi6[i - 1] < rsi14[i - 1]  # type: ignore[operator]
        ):
            rsi_buy[i] = close[i - 1]
        if (
            rsi[i] > th["rsi_sell"]  # type: ignore[operator]
            and rsi6[i] < rsi14[i]  # type: ignore[operator]
            and rsi6[i - 1] > rsi14[i - 1]  # type: ignore[operator]
        ):
            rsi_sell[i] = close[i - 1]

    # 扩展因子序列（BOLL/CCI/DMI/MFI/量能/52 周位置）。
    # 公式放在 composite_factors 共享模块，与回测引擎逐位一致（parity）。
    factor_series = compute_extra_factor_series(close, high, low, volume)
    bolu = factor_series["bolu"]
    bold = factor_series["bold"]
    cci = factor_series["cci"]

    # OBV = IF(Volume>OBVprev, OBVprev+Volume, OBVprev-Volume)（Excel 原逻辑）
    obv: List[float] = [0.0] * n
    if n:
        obv[0] = volume[0]
        for i in range(1, n):
            if volume[i] > obv[i - 1]:
                obv[i] = obv[i - 1] + volume[i]
            else:
                obv[i] = obv[i - 1] - volume[i]
    obv_ma = {str(p): _sma(obv, p) for p in OBV_PERIODS}

    # OBV triggers
    obv_buy: List[Optional[float]] = [None] * n
    obv_sell: List[Optional[float]] = [None] * n
    for i in range(n):
        o5, o10, o20, o40, o60 = (
            obv_ma["5"][i], obv_ma["10"][i], obv_ma["20"][i],
            obv_ma["40"][i], obv_ma["60"][i],
        )
        if None in (o5, o10, o20, o40, o60, bolu[i], bold[i]):
            continue
        upper = bolu[i]  # type: ignore[assignment]
        lower = bold[i]  # type: ignore[assignment]
        if (
            o5 > o10 and o5 > o20 and o5 > o40 and o5 > o60  # type: ignore[operator]
            and close[i] < (lower + th["bol_constant"] * (upper - lower))
        ):
            obv_buy[i] = close[i]
        if (
            o5 < o10 and o5 < o20 and o5 < o40 and o5 < o60  # type: ignore[operator]
            and close[i] > (upper - th["bol_constant"] * (upper - lower))
        ):
            obv_sell[i] = close[i]

    # ---- 复合 BUY/SELL 评分（归一化，不依赖绝对价格量级） ----
    # 所有判断只使用截止当前 bar 的数据，无未来函数（look-ahead bias）。
    lookback = max(2, int(th["macd_lookback"]))
    trend_period = max(2, int(th["trend_period"]))
    sma_trend = _sma(close, trend_period)
    buy_threshold = int(th["composite_buy_threshold"])
    sell_threshold = int(th["composite_sell_threshold"])
    momentum_period = max(1, int(th["momentum_period"]))

    # ------------------------------------------------------------
    # 价格动量 / 动量改善
    #
    # momentum_pct:
    #     近 N 根涨跌幅 ROC（%）。
    #
    # momentum_delta:
    #     ROC 相对上一根 bar 的变化。
    #
    # BUY 需同时满足：
    #     1. 动量正在改善
    #     2. 当日价格确实在上涨
    #
    # SELL 需同时满足：
    #     1. 动量正在恶化
    #     2. 当日价格确实在下跌
    #
    # 避免在整体下跌的 bar 上，微小的正 ROC 变化自动变成 BUY 加分。
    # ------------------------------------------------------------

    momentum_pct: List[Optional[float]] = [None] * n

    for i in range(momentum_period, n):

        prev_close = close[i - momentum_period]

        if prev_close == 0:
            continue

        momentum_pct[i] = (
            (close[i] - prev_close)
            / prev_close
            * 100.0
        )

    momentum_delta: List[Optional[float]] = [None] * n

    for i in range(1, n):

        if (
            momentum_pct[i] is None
            or momentum_pct[i - 1] is None
        ):
            continue

        momentum_delta[i] = (
            momentum_pct[i]
            - momentum_pct[i - 1]
        )  # type: ignore[operator]

    buy_score: List[int] = [0] * n
    sell_score: List[int] = [0] * n
    buy_signal: List[Optional[float]] = [None] * n
    sell_signal: List[Optional[float]] = [None] * n
    buy_breakdown: List[Dict[str, int]] = [{} for _ in range(n)]
    sell_breakdown: List[Dict[str, int]] = [{} for _ in range(n)]

    # 扩展因子评分器（权重默认 0 → 不贡献分数，与改造前输出一致）
    extra_scorer = ExtraFactorScorer(factor_series, close, volume, th)

    for i in range(n):
        # MACD 归一化：滚动窗口百分位（仅使用当前 bar 之前的数据，
        # 且要求完整回看窗口，避免早期样本过少导致百分位失真）。
        # 评分公式本身由 strategy_scoring.score_bar 唯一实现，
        # 此处仅组装单 bar 特征并委托打分（与回测引擎同源）。
        if i >= lookback:
            macd_pct = _percentile_rank(macd[i - lookback:i], macd[i])
            macd_rising = macd[i] > macd[i - 1]
            macd_falling = macd[i] < macd[i - 1]
        else:
            macd_pct = None
            macd_rising = False
            macd_falling = False
        extra_buy, extra_sell, extra_bd, extra_sd = extra_scorer.score_at(i)
        scored = score_bar(
            BarFeatures(
                macd_pct=macd_pct,
                macd_rising=macd_rising,
                macd_declining=macd_falling,
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
            th,
        )
        buy_score[i] = scored.buy
        sell_score[i] = scored.sell
        buy_breakdown[i] = scored.buy_breakdown
        sell_breakdown[i] = scored.sell_breakdown

        # 信号仅在评分“进入”阈值区间的那根 bar 触发，保持图表整洁；
        # 同一根 bar 买卖同时进入区间时视为方向不明，不产生任何标记。
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

    extra_max = extra_scorer.max_extra()
    triggers = {
        "macd_buy": macd_buy,
        "macd_sell": macd_sell,
        "kdj_buy": kdj_buy,
        "kdj_sell": kdj_sell,
        "rsi_buy": rsi_buy,
        "rsi_sell": rsi_sell,
        "obv_buy": obv_buy,
        "obv_sell": obv_sell,
    }
    triggers.update(compute_extra_triggers(factor_series, close, th))

    return {
        "dates": dates,
        "close": close,
        "sma": sma,
        "ema": ema,
        "macd": macd,
        "macd_signal": macd_signal,
        "k": k_values,
        "d": d_values,
        "j": j_values,
        "rsi": rsi,
        "rsi6": rsi6,
        "rsi14": rsi14,
        "bolu": bolu,
        "bold": bold,
        "cci": cci,
        "obv": obv,
        "obv_ma": obv_ma,
        "triggers": triggers,
        "composite": {
            "buy_score": buy_score,
            "sell_score": sell_score,
            "buy_signal": buy_signal,
            "sell_signal": sell_signal,
            "buy_breakdown": buy_breakdown,
            "sell_breakdown": sell_breakdown,
            # 满分 = 经典 10 分 + 启用扩展因子权重和（默认权重 0 时仍为 10）
            "max_buy_score": MAX_BUY_SCORE + extra_max,
            "max_sell_score": MAX_SELL_SCORE + extra_max,
        },
    }
