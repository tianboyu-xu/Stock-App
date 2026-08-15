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
import statistics
from typing import Any, Dict, List, Optional, Sequence

# Excel "Today" 工作表第 52 行的默认阈值
DEFAULT_THRESHOLDS: Dict[str, float] = {
    "bol_constant": 0.1,   # F52 BOL constant
    "macd_buy": 0.7,       # G52 MACD Buy
    "macd_sell": 0.99,     # H52 MACD Sell
    "kdj_buy": 40.0,       # I52 KDJ Buy
    "kdj_sell": 70.0,      # J52 KDJ Sell
    "rsi_buy": 10.0,       # K52 RSI Buy
    "rsi_sell": 70.0,      # L52 RSI Sell
}

SMA_PERIODS = [5, 9, 10, 12, 20, 26, 30, 40, 50, 60, 120, 200]
EMA_PERIODS = [5, 9, 12, 20, 26, 40, 60, 120, 200]
OBV_PERIODS = [5, 10, 20, 40, 60]


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
            },
        }
        所有序列与输入等长，触发器序列为收盘价或 None。
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

    # MACD = EMA12 - EMA26; Signal = EMA9(MACD)
    ema12 = ema["12"]
    ema26 = ema["26"]
    macd: List[float] = [
        (ema12[i] or 0.0) - (ema26[i] or 0.0) for i in range(n)
    ]
    macd_signal = _ema(macd, 9)

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

    # RSV = (Close - MIN(Low,9)) / (MAX(High,9) - MIN(Low,9)) * 100
    low_min9 = _rolling_min(low, 9)
    high_max9 = _rolling_max(high, 9)
    rsv: List[Optional[float]] = [None] * n
    for i in range(n):
        if low_min9[i] is not None and high_max9[i] is not None:
            denom = high_max9[i] - low_min9[i]  # type: ignore[operator]
            rsv[i] = 0.0 if denom == 0 else (close[i] - low_min9[i]) / denom * 100.0  # type: ignore[operator]

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

    # RSI：%Gain/%Loss -> RS -> RSI(30~70) -> RSI6/RSI14
    gains: List[float] = [0.0] * n
    losses: List[float] = [0.0] * n
    for i in range(1, n):
        if close[i] > close[i - 1]:
            gains[i] = (close[i] - close[i - 1]) / close[i - 1]
        elif close[i] < close[i - 1]:
            losses[i] = (close[i - 1] - close[i]) / close[i - 1]

    rsi: List[Optional[float]] = [None] * n
    for i in range(n):
        if i < 14:
            rsi[i] = None
            continue
        sum_gain = sum(gains[i - 14: i])      # SUM(AP[r-14..r-1])
        sum_loss = sum(losses[i - 14: i])
        avg_gain = (sum_gain / 14.0 * 13.0 + gains[i]) / 14.0
        avg_loss = (sum_loss / 14.0 * 13.0 + losses[i]) / 14.0
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

    rsi6 = _avg_opt(rsi, 6)
    rsi14 = _avg_opt(rsi, 14)

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

    # BOLL：BOLU/BOLD = AVERAGE(TP,20) ± 2*STDEV(TP,20)
    bolu: List[Optional[float]] = [None] * n
    bold: List[Optional[float]] = [None] * n
    for i in range(n):
        if i + 1 < 20:
            continue
        window = typical[i + 1 - 20: i + 1]
        mean = sum(window) / 20.0
        stdev = statistics.pstdev(window) if len(window) > 1 else 0.0
        bolu[i] = mean + 2.0 * stdev
        bold[i] = mean - 2.0 * stdev

    # CCI = (TP - AVERAGE(TP,14)) / (0.015 * AVEDEV(TP,14))
    cci: List[Optional[float]] = [None] * n
    for i in range(n):
        if i + 1 < 14:
            continue
        window = typical[i + 1 - 14: i + 1]
        mean = sum(window) / 14.0
        avedev = sum(abs(v - mean) for v in window) / 14.0
        denom = 0.015 * avedev
        cci[i] = 0.0 if denom == 0 else (typical[i] - mean) / denom

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
        "triggers": {
            "macd_buy": macd_buy,
            "macd_sell": macd_sell,
            "kdj_buy": kdj_buy,
            "kdj_sell": kdj_sell,
            "rsi_buy": rsi_buy,
            "rsi_sell": rsi_sell,
            "obv_buy": obv_buy,
            "obv_sell": obv_sell,
        },
    }
