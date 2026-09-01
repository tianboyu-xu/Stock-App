# -*- coding: utf-8 -*-
"""
复合评分扩展因子库（indicator_service 与 strategy_backtester 共享）
================================================================

所有扩展因子只依赖日线 OHLCV，只使用截止当前 bar 的数据，无未来函数。
两个消费方（技术指标图 / Auto Tune 回测引擎）都调用这里的同一份公式，
保证图表标记、复合评分与回测信号逐位一致（parity）。

因子一览（每个因子由“触发水平 + 权重”控制，权重 0 = 不参与复合评分）：

    boll    BOLL %B：下穿低位后上穿 buy 水平看多 / 上穿高位后下穿 sell 水平看空
    cci     CCI(14)：上穿低位水平看多 / 下穿高位水平看空
    dmi     DMI(14)：+DI 上穿 -DI 且 ADX >= 触发水平看多，反向看空
    mfi     MFI(14)：上穿低位水平看多 / 下穿高位水平看空
    volume  量能确认：volume/SMA20(volume) >= 触发水平，按当日涨跌方向计分
    range52 52 周位置：接近 252 日最高看多 / 接近 252 日最低看空

权重为整数点数（默认 0）：权重 0 时因子完全不贡献分数，因此旧代际
（A-D）保持默认权重 0 时，复合评分输出与改造前完全一致。
"""

from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional, Sequence

# 复合评分中扩展因子的分解键（并入 buy/sell_breakdown）
FACTOR_BREAKDOWN_KEYS = ("boll", "cci", "dmi", "mfi", "volume", "range52")

# 图表触发器组（compute_indicators["triggers"] 中新增的买卖标记）
EXTRA_TRIGGER_GROUPS = ("boll", "cci", "dmi", "mfi")

# 各因子的权重阈值键（分数为整数点数，0 = 禁用）
FACTOR_WEIGHT_KEYS = {
    "boll": "boll_weight",
    "cci": "cci_weight",
    "dmi": "dmi_weight",
    "mfi": "mfi_weight",
    "volume": "volume_weight",
    "range52": "range52_weight",
}

# 事件型因子（boll/cci/dmi/mfi）：评分与图表标记共用同一触发条件
_EVENT_GROUPS = ("boll", "cci", "dmi", "mfi")


def compute_extra_factor_series(
    close: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    volume: Sequence[float],
) -> Dict[str, List[Optional[float]]]:
    """计算与阈值无关的扩展因子序列（两个消费方的公式完全一致）。

    返回键：
        bolu, bold          BOLL 上下轨（TP 20 日均 ± 2 倍总体标准差，Excel 口径）
        cci                 CCI(14)（TP 口径）
        plus_di, minus_di   DMI(14) 方向线（Wilder 平滑）
        adx                 ADX(14)（DX 序列再 Wilder 平滑）
        mfi                 MFI(14)（典型价 × 成交量资金流量）
        vol_sma20           SMA20(volume)
        high252             rolling_max(high, 252)
        low252              rolling_min(low, 252)
    """
    n = len(close)
    typical = [(high[i] + low[i] + close[i]) / 3.0 for i in range(n)]

    def _sma(values: Sequence[float], period: int) -> List[Optional[float]]:
        out: List[Optional[float]] = [None] * n
        for i in range(n):
            if i + 1 < period:
                continue
            window = values[i + 1 - period: i + 1]
            out[i] = sum(window) / period
        return out

    def _rolling_min(values: Sequence[float], period: int) -> List[Optional[float]]:
        out: List[Optional[float]] = [None] * n
        for i in range(n):
            if i + 1 < period:
                continue
            out[i] = min(values[i + 1 - period: i + 1])
        return out

    def _rolling_max(values: Sequence[float], period: int) -> List[Optional[float]]:
        out: List[Optional[float]] = [None] * n
        for i in range(n):
            if i + 1 < period:
                continue
            out[i] = max(values[i + 1 - period: i + 1])
        return out

    # BOLL：BOLU/BOLD = AVERAGE(TP,20) ± 2*STDEV(TP,20)（与 Excel "300 Plot" 一致）
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

    # CCI = (TP - AVERAGE(TP,14)) / (0.015 * AVEDEV(TP,14))（Excel 口径）
    cci: List[Optional[float]] = [None] * n
    for i in range(n):
        if i + 1 < 14:
            continue
        window = typical[i + 1 - 14: i + 1]
        mean = sum(window) / 14.0
        avedev = sum(abs(v - mean) for v in window) / 14.0
        denom = 0.015 * avedev
        cci[i] = 0.0 if denom == 0 else (typical[i] - mean) / denom

    # DMI / ADX(14)：Wilder 平滑口径（TR、+DM、-DM、DX 全部用同一约定）
    tr: List[float] = [0.0] * n
    plus_dm: List[float] = [0.0] * n
    minus_dm: List[float] = [0.0] * n
    for i in range(n):
        if i == 0:
            tr[i] = high[i] - low[i]
            continue
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        plus_dm[i] = up_move if up_move > down_move and up_move > 0.0 else 0.0
        minus_dm[i] = down_move if down_move > up_move and down_move > 0.0 else 0.0

    def _wilder(values: Sequence[float], period: int) -> List[Optional[float]]:
        out: List[Optional[float]] = [None] * n
        prev: Optional[float] = None
        for i in range(n):
            if i + 1 < period:
                continue
            if prev is None:
                prev = sum(values[: i + 1]) / period
            else:
                prev = prev * (period - 1) / period + values[i]
            out[i] = prev
        return out

    atr_w = _wilder(tr, 14)
    plus_di_raw = _wilder(plus_dm, 14)
    minus_di_raw = _wilder(minus_dm, 14)
    plus_di: List[Optional[float]] = [None] * n
    minus_di: List[Optional[float]] = [None] * n
    dx: List[float] = [0.0] * n
    for i in range(n):
        if atr_w[i] in (None, 0.0):
            continue
        plus_di[i] = plus_di_raw[i] * 100.0 / atr_w[i]  # type: ignore[operator]
        minus_di[i] = minus_di_raw[i] * 100.0 / atr_w[i]  # type: ignore[operator]
        total_di = plus_di[i] + minus_di[i]  # type: ignore[operator]
        if total_di:
            dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / total_di  # type: ignore[operator]
    adx = _wilder(dx, 14)

    # MFI(14)：典型价 × 成交量的正/负资金流量，14 日窗口求和
    pos_flow: List[float] = [0.0] * n
    neg_flow: List[float] = [0.0] * n
    for i in range(1, n):
        money_flow = typical[i] * volume[i]
        if typical[i] > typical[i - 1]:
            pos_flow[i] = money_flow
        elif typical[i] < typical[i - 1]:
            neg_flow[i] = money_flow
    mfi: List[Optional[float]] = [None] * n
    for i in range(n):
        if i + 1 < 14:
            continue
        pos_sum = sum(pos_flow[i - 13: i + 1])
        neg_sum = sum(neg_flow[i - 13: i + 1])
        mfi[i] = 100.0 if neg_sum == 0.0 else 100.0 - 100.0 / (1.0 + pos_sum / neg_sum)

    return {
        "bolu": bolu,
        "bold": bold,
        "cci": cci,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "adx": adx,
        "mfi": mfi,
        "vol_sma20": _sma(volume, 20),
        "high252": _rolling_max(high, 252),
        "low252": _rolling_min(low, 252),
    }


def factor_events_at(
    series: Dict[str, Sequence[Optional[float]]],
    close: Sequence[float],
    i: int,
    thresholds: Dict[str, float],
) -> Dict[str, Optional[str]]:
    """bar i 的事件型因子方向：{'boll': 'buy'/'sell'/None, ...}。

    事件条件与复合评分、图表标记完全一致：
        buy  = 指标向上穿越 buy 水平（前值低于水平、当前值不低于水平）
        sell = 指标向下穿越 sell 水平（前值高于水平、当前值不高于水平）
        dmi  = +DI/-DI 交叉且 ADX 达到触发水平
    """
    events: Dict[str, Optional[str]] = {group: None for group in _EVENT_GROUPS}
    if i < 1:
        return events

    # BOLL %B
    bolu = series["bolu"]
    bold = series["bold"]
    if None not in (bolu[i - 1], bold[i - 1], bolu[i], bold[i]):
        denom_prev = bolu[i - 1] - bold[i - 1]  # type: ignore[operator]
        denom_cur = bolu[i] - bold[i]  # type: ignore[operator]
        if denom_prev > 0 and denom_cur > 0:
            pb_prev = (close[i - 1] - bold[i - 1]) / denom_prev  # type: ignore[operator]
            pb_cur = (close[i] - bold[i]) / denom_cur  # type: ignore[operator]
            buy_level = float(thresholds["boll_buy_level"])
            sell_level = float(thresholds["boll_sell_level"])
            if pb_prev < buy_level <= pb_cur:
                events["boll"] = "buy"
            elif pb_prev > sell_level >= pb_cur:
                events["boll"] = "sell"

    # CCI
    cci = series["cci"]
    if None not in (cci[i - 1], cci[i]):
        buy_level = float(thresholds["cci_buy_level"])
        sell_level = float(thresholds["cci_sell_level"])
        if cci[i - 1] < buy_level <= cci[i]:  # type: ignore[operator]
            events["cci"] = "buy"
        elif cci[i - 1] > sell_level >= cci[i]:  # type: ignore[operator]
            events["cci"] = "sell"

    # DMI：+DI/-DI 交叉 + ADX 趋势强度确认
    plus_di = series["plus_di"]
    minus_di = series["minus_di"]
    adx = series["adx"]
    if None not in (
        plus_di[i - 1], minus_di[i - 1], plus_di[i], minus_di[i], adx[i],
    ):
        adx_level = float(thresholds["adx_min_level"])
        if adx[i] >= adx_level:  # type: ignore[operator]
            if (
                plus_di[i - 1] <= minus_di[i - 1]  # type: ignore[operator]
                and plus_di[i] > minus_di[i]  # type: ignore[operator]
            ):
                events["dmi"] = "buy"
            elif (
                plus_di[i - 1] >= minus_di[i - 1]  # type: ignore[operator]
                and plus_di[i] < minus_di[i]  # type: ignore[operator]
            ):
                events["dmi"] = "sell"

    # MFI
    mfi = series["mfi"]
    if None not in (mfi[i - 1], mfi[i]):
        buy_level = float(thresholds["mfi_buy_level"])
        sell_level = float(thresholds["mfi_sell_level"])
        if mfi[i - 1] < buy_level <= mfi[i]:  # type: ignore[operator]
            events["mfi"] = "buy"
        elif mfi[i - 1] > sell_level >= mfi[i]:  # type: ignore[operator]
            events["mfi"] = "sell"

    return events


class ExtraFactorScorer:
    """在预计算序列上按阈值给出扩展因子得分（整数点数，权重 0 = 禁用）。"""

    def __init__(
        self,
        series: Dict[str, Sequence[Optional[float]]],
        close: Sequence[float],
        volume: Sequence[float],
        thresholds: Dict[str, float],
    ) -> None:
        self._series = series
        self._close = close
        self._volume = volume
        self._th = thresholds
        self._weights = {
            group: self._points(FACTOR_WEIGHT_KEYS[group])
            for group in FACTOR_BREAKDOWN_KEYS
        }

    def _points(self, weight_key: str) -> int:
        return max(0, int(float(self._th[weight_key])))

    def max_extra(self) -> int:
        """扩展因子可贡献的最大分数（buy/sell 对称）。"""
        return sum(self._weights.values())

    def score_at(
        self, i: int,
    ) -> tuple[int, int, Dict[str, int], Dict[str, int]]:
        """返回 (buy 分数, sell 分数, buy 分解, sell 分解)。"""
        bd: Dict[str, int] = {key: 0 for key in FACTOR_BREAKDOWN_KEYS}
        sd: Dict[str, int] = {key: 0 for key in FACTOR_BREAKDOWN_KEYS}
        buy = 0
        sell = 0

        # 事件型因子（boll/cci/dmi/mfi）：与图表标记同一触发条件
        events = factor_events_at(self._series, self._close, i, self._th)
        for group, direction in events.items():
            weight = self._weights[group]
            if not weight or direction is None:
                continue
            if direction == "buy":
                bd[group] = weight
                buy += weight
            else:
                sd[group] = weight
                sell += weight

        # 量能确认：volume/SMA20(volume) 达标时按当日涨跌方向计分
        weight = self._weights["volume"]
        if weight and i >= 1:
            vol_sma20 = self._series["vol_sma20"][i]
            if vol_sma20:
                ratio = self._volume[i] / vol_sma20
                if ratio >= float(self._th["volume_confirm_level"]):
                    if self._close[i] > self._close[i - 1]:
                        bd["volume"] = weight
                        buy += weight
                    elif self._close[i] < self._close[i - 1]:
                        sd["volume"] = weight
                        sell += weight

        # 52 周位置：接近 252 日最高看多 / 接近 252 日最低看空
        weight = self._weights["range52"]
        if weight:
            high252 = self._series["high252"][i]
            low252 = self._series["low252"][i]
            if high252 and self._close[i] / high252 >= float(
                self._th["range52_high_level"]
            ):
                bd["range52"] = weight
                buy += weight
            if low252 and self._close[i] / low252 <= float(
                self._th["range52_low_level"]
            ):
                sd["range52"] = weight
                sell += weight

        return buy, sell, bd, sd


def compute_extra_triggers(
    series: Dict[str, Sequence[Optional[float]]],
    close: Sequence[float],
    thresholds: Dict[str, float],
) -> Dict[str, List[Optional[float]]]:
    """事件型因子（boll/cci/dmi/mfi）的图表买卖标记序列（收盘价或 None）。

    与 ExtraFactorScorer 共用同一事件条件，保证图表标记与评分语义一致。
    """
    n = len(close)
    output: Dict[str, List[Optional[float]]] = {
        f"{group}_{direction}": [None] * n
        for group in EXTRA_TRIGGER_GROUPS
        for direction in ("buy", "sell")
    }
    for i in range(1, n):
        events = factor_events_at(series, close, i, thresholds)
        for group, direction in events.items():
            if direction:
                output[f"{group}_{direction}"][i] = close[i]
    return output
