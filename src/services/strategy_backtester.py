# -*- coding: utf-8 -*-
"""
策略回测引擎（Auto Tune 专用）
================================

为技术指标图 "Auto Tune" 提供确定性的历史回测：

1. `prepare_base_series` 一次性计算与阈值无关的基础指标序列
   （公式与 indicator_service 完全一致，复用其 SMA/EMA/滚动窗口函数）。
2. `compute_composite_signals` 按给定阈值复刻 indicator_service 的复合
   BUY/SELL 评分逻辑（MACD 滚动百分位 + KDJ 反转 + RSI 反转 + 趋势
   regime + 价格动量改善/恶化 + 扩展因子 BOLL/CCI/DMI/MFI/量能/52 周
   位置，扩展因子权重默认 0、公式与 indicator_service 共享同一模块），
   使用有序窗口加速百分位计算（窗口
   不含当前 bar 且要求完整回看窗口），信号仅在评分进入阈值区间的
   bar 触发（同 bar 双向进入视为方向不明、不触发），结果与
   compute_indicators 一致。
3. `simulate_trades` 按 "信号收盘确认、次日开盘成交" 的执行假设模拟
   交易：默认最多每 window_days 根交易日一次买入；C/D 策略叠加
   ATR 止损与 ATR 移动止盈（盘中触发按止损价成交，跳空按开盘价）。
4. `summarize_metrics` 输出 CAGR / Sharpe / Sortino / 最大回撤 /
   盈亏比 / 交易次数 / 平均单笔收益等指标。
5. `objective_score` 是平衡收益、回撤、风险调整收益、交易质量与信号
   频率的综合目标函数，不单独最大化历史收益率。

所有计算只使用截止当前 bar 的数据，无未来函数。
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right, insort
from typing import Any, Dict, List, Optional, Sequence

from src.services.composite_factors import (
    ExtraFactorScorer,
    compute_extra_factor_series,
)
from src.services.indicator_service import (
    DEFAULT_THRESHOLDS,
    _ema,
    _rolling_max,
    _rolling_min,
    _sma,
)

TRADING_DAYS_PER_YEAR = 252
# 单边交易成本（佣金+滑点近似），用于策略比较，非投资建议。
DEFAULT_COST_PCT_PER_SIDE = 0.1
# 美国资本利得税近似税率（%，按家庭应税收入约 40 万美元档）：
# - 短期（持有不足一年）并入普通所得计税，该收入档边际税率约 35%；
# - 长期（持有满一年）适用长期资本利得税率，该收入档为 15%。
# 对每笔正收益计税、亏损不抵扣，仅用于税后收益展示与基准对比，不构成税务建议。
DEFAULT_SHORT_TERM_TAX_PCT = 35.0
DEFAULT_LONG_TERM_TAX_PCT = 15.0
# 持有达到约一年（252 个交易日）的交易按长期税率计税
LONG_TERM_HOLDING_BARS = TRADING_DAYS_PER_YEAR


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def prepare_base_series(bars: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """一次性计算与阈值无关的指标序列（公式与 indicator_service 一致）。"""
    n = len(bars)
    dates = [str(b.get("date", "")) for b in bars]
    close = [float(b["close"]) for b in bars]
    high = [float(b["high"]) for b in bars]
    low = [float(b["low"]) for b in bars]
    volume = [float(b.get("volume") or 0.0) for b in bars]

    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    macd = [(ema12[i] or 0.0) - (ema26[i] or 0.0) for i in range(n)]
    macd_signal = _ema(macd, 9)

    # KDJ(9,3,3)，与 indicator_service 相同的 RSV/K/D 递推。
    low_min9 = _rolling_min(low, 9)
    high_max9 = _rolling_max(high, 9)
    k_values: List[Optional[float]] = [None] * n
    d_values: List[Optional[float]] = [None] * n
    k_prev = 50.0
    d_prev = 50.0
    for i in range(n):
        if low_min9[i] is None or high_max9[i] is None:
            continue
        denom = high_max9[i] - low_min9[i]  # type: ignore[operator]
        rsv = 50.0 if denom == 0 else (close[i] - low_min9[i]) / denom * 100.0  # type: ignore[operator]
        k_cur = rsv / 3.0 + k_prev * 2.0 / 3.0
        d_cur = k_cur / 3.0 + d_prev * 2.0 / 3.0
        k_values[i] = k_cur
        d_values[i] = d_cur
        k_prev = k_cur
        d_prev = d_cur

    # RSI(14) 与 RSI6（RSI 的 6 日均值），Excel 口径。
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
            continue
        sum_gain = sum(gains[i - 14: i])
        sum_loss = sum(losses[i - 14: i])
        avg_gain = (sum_gain / 14.0 * 13.0 + gains[i]) / 14.0
        avg_loss = (sum_loss / 14.0 * 13.0 + losses[i]) / 14.0
        rsi[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

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


def compute_composite_signals(
    base: Dict[str, Any],
    thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, List[Any]]:
    """按 indicator_service 复合评分逻辑计算 BUY/SELL 信号。

    与 compute_indicators 的 composite 输出保持一致；MACD 滚动百分位用
    有序窗口实现（窗口仅含当前 bar 之前的数据且要求完整回看窗口，
    等价于逐窗 `_percentile_rank`），复杂度 O(n log w)。
    """
    th = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        for key, value in thresholds.items():
            if key in th and value is not None:
                try:
                    th[key] = float(value)
                except (TypeError, ValueError):
                    pass

    n = base["n"]
    close: List[float] = base["close"]
    macd: List[float] = base["macd"]
    k_values: List[Optional[float]] = base["k"]
    d_values: List[Optional[float]] = base["d"]
    rsi: List[Optional[float]] = base["rsi"]
    rsi6: List[Optional[float]] = base["rsi6"]
    volume: List[float] = base.get("volume", [0.0] * n)
    # 扩展因子序列优先取 prepare_base_series 的共享结果；缺失时按同口径
    # 现场补算（保证与 indicator_service 的 parity 仍然成立）。
    factor_series = base.get("factor_series") or compute_extra_factor_series(
        base["close"], base["high"], base["low"], volume
    )
    extra_scorer = ExtraFactorScorer(factor_series, close, volume, th)

    lookback = max(2, int(th["macd_lookback"]))
    trend_period = max(2, int(th["trend_period"]))
    sma_trend = _sma(close, trend_period)

    buy_score: List[int] = [0] * n
    sell_score: List[int] = [0] * n
    buy_signal: List[Optional[float]] = [None] * n
    sell_signal: List[Optional[float]] = [None] * n

    # 有序窗口维护 MACD 滚动百分位（窗口仅含当前 bar 之前的数据，
    # 等价于 count(v <= current) / len(prior_window) * 100）。
    window_sorted: List[float] = []
    buy_threshold = int(th["composite_buy_threshold"])
    sell_threshold = int(th["composite_sell_threshold"])
    kdj_low = th["kdj_low"]
    kdj_high = th["kdj_high"]
    rsi_os = th["rsi_low"]
    rs_ob = th["rsi_high"]
    macd_low_pct = th["macd_low_percentile"]
    macd_high_pct = th["macd_high_percentile"]
    momentum_period = max(1, int(th["momentum_period"]))
    momentum_min_change_pct = float(
        th["momentum_min_change_pct"]
    )

    # ------------------------------------------------------------
    # 价格动量 / 动量改善（与 indicator_service 保持一致）
    #
    # momentum_pct:
    #     近 N 根涨跌幅 ROC（%）。
    #
    # momentum_delta:
    #     ROC 相对上一根 bar 的变化。
    #
    # BUY 需同时满足：动量正在改善 且 当日价格确实在上涨。
    # SELL 需同时满足：动量正在恶化 且 当日价格确实在下跌。
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

        b = 0
        s = 0

        macd_rising = i >= 1 and macd[i] > macd[i - 1]
        macd_declining = i >= 1 and macd[i] < macd[i - 1]

        # 深跌低位 + 向上反转 / 高位 + 向下反转
        if (
            macd_pct is not None
            and macd_pct <= macd_low_pct
            and macd_rising
        ):
            b += 2
        if (
            macd_pct is not None
            and macd_pct >= macd_high_pct
            and macd_declining
        ):
            s += 2

        # KDJ 超卖金叉 / 超买死叉
        if i >= 1 and None not in (k_values[i], d_values[i], k_values[i - 1], d_values[i - 1]):
            golden_cross = (
                k_values[i] > d_values[i]  # type: ignore[operator]
                and k_values[i - 1] <= d_values[i - 1]  # type: ignore[operator]
            )
            death_cross = (
                k_values[i] < d_values[i]  # type: ignore[operator]
                and k_values[i - 1] >= d_values[i - 1]  # type: ignore[operator]
            )
            if (
                k_values[i] < kdj_low  # type: ignore[operator]
                and d_values[i] < kdj_low  # type: ignore[operator]
                and golden_cross
            ):
                b += 2
            if (
                k_values[i] > kdj_high  # type: ignore[operator]
                and d_values[i] > kdj_high  # type: ignore[operator]
                and death_cross
            ):
                s += 2

        # RSI 极端 + 反转（快速平滑 RSI 转向）
        if i >= 1 and None not in (rsi[i], rsi6[i], rsi6[i - 1]):
            if rsi[i] < rsi_os and rsi6[i] > rsi6[i - 1]:  # type: ignore[operator]
                b += 2
            if rsi[i] > rs_ob and rsi6[i] < rsi6[i - 1]:  # type: ignore[operator]
                s += 2

        # 长期趋势 regime：价格相对趋势均线 + 均线方向（各 0-1 分，BUY/SELL 对称）
        if sma_trend[i] is not None:
            if close[i] > sma_trend[i]:  # type: ignore[operator]
                b += 1
            elif close[i] < sma_trend[i]:  # type: ignore[operator]
                s += 1

            if i >= 1 and sma_trend[i - 1] is not None:
                if sma_trend[i] > sma_trend[i - 1]:  # type: ignore[operator]
                    b += 1
                elif sma_trend[i] < sma_trend[i - 1]:  # type: ignore[operator]
                    s += 1

        # ------------------------------------------------------------
        # 动量改善 / 恶化（与 indicator_service 保持一致）
        #
        # BUY：ROC 正在改善 且 当日收盘高于昨日收盘
        # SELL：ROC 正在恶化 且 当日收盘低于昨日收盘
        # ------------------------------------------------------------
        delta = momentum_delta[i]

        if delta is not None:

            if (
                delta > momentum_min_change_pct
                and i >= 1
                and close[i] > close[i - 1]
            ):
                b += 2

            elif (
                delta < -momentum_min_change_pct
                and i >= 1
                and close[i] < close[i - 1]
            ):
                s += 2

        # 扩展因子（BOLL/CCI/DMI/MFI/量能/52 周位置）：权重 0 时零贡献，
        # 与 compute_indicators 的评分公式完全一致（共享 composite_factors）
        extra_buy, extra_sell, _, _ = extra_scorer.score_at(i)
        b += extra_buy
        s += extra_sell

        buy_score[i] = b
        sell_score[i] = s

        # 信号仅在评分“进入”阈值区间的那根 bar 触发，与 compute_indicators 一致；
        # 同一根 bar 买卖同时进入区间时视为方向不明，不产生任何标记。
        prev_buy = buy_score[i - 1] if i > 0 else 0
        prev_sell = sell_score[i - 1] if i > 0 else 0
        buy_enter = b >= buy_threshold and prev_buy < buy_threshold
        sell_enter = s >= sell_threshold and prev_sell < sell_threshold
        if buy_enter and not sell_enter:
            buy_signal[i] = close[i]
        elif sell_enter and not buy_enter:
            sell_signal[i] = close[i]

    return {
        "buy_score": buy_score,
        "sell_score": sell_score,
        "buy_signal": buy_signal,
        "sell_signal": sell_signal,
    }


def simulate_trades(
    base: Dict[str, Any],
    signals: Dict[str, List[Any]],
    start_index: int,
    end_index: int,
    window_days: int = 90,
    cost_pct_per_side: float = DEFAULT_COST_PCT_PER_SIDE,
    use_trend_filter: bool = False,
    use_volume_filter: bool = False,
    stop_multiple_atr: Optional[float] = None,
    trail_multiple_atr: Optional[float] = None,
) -> Dict[str, Any]:
    """在 [start_index, end_index] 区间内模拟交易（其余参数见模块 docstring）。

    执行假设：
    - 信号在收盘确认，次日开盘价成交（无同日收盘执行）。
    - 两次买入之间至少间隔 window_days 根交易日（默认 90，即最多约
      一个季度一次往返）。
    - ATR 止损/移动止盈用入场时的 ATR(14)；盘中跌破按止损价成交，
      跳空低开按开盘价成交；移动止盈以持仓期间最高收盘价为基准。
    - 区间结束时仍持仓则按区间最后收盘价强制平仓。
    """
    close: List[float] = base["close"]
    open_: List[float] = base["open"]
    low: List[float] = base["low"]
    dates: List[str] = base["dates"]
    atr: List[Optional[float]] = base["atr"]
    sma200: List[Optional[float]] = base["sma200"]
    vol_sma20: List[Optional[float]] = base["vol_sma20"]
    volume: List[float] = base["volume"]
    buy_signal: List[Optional[float]] = signals["buy_signal"]
    sell_signal: List[Optional[float]] = signals["sell_signal"]

    cost = cost_pct_per_side / 100.0
    trades: List[Dict[str, Any]] = []
    equity = [1.0] * (end_index - start_index + 1)
    realized = 1.0
    holding_bars = 0
    entry_i: Optional[int] = None
    entry_price = 0.0
    stop_level: Optional[float] = None
    trail_level: Optional[float] = None
    highest_close = 0.0
    last_entry_index: Optional[int] = None

    def close_trade(exit_i: int, exit_price: float, reason: str) -> None:
        nonlocal entry_i, entry_price, holding_bars, realized
        assert entry_i is not None
        net_exit = exit_price * (1.0 - cost)
        trade_return = (net_exit / entry_price - 1.0) * 100.0
        trades.append({
            "entry_date": dates[entry_i],
            "exit_date": dates[exit_i],
            "entry_price": round(entry_price, 4),
            "exit_price": round(net_exit, 4),
            "return_pct": round(trade_return, 4),
            "bars_held": exit_i - entry_i,
            "exit_reason": reason,
        })
        realized *= 1.0 + trade_return / 100.0
        entry_i = None
        holding_bars = 0

    pending_entry = False
    pending_exit = False
    for i in range(start_index, end_index + 1):
        offset = i - start_index

        # ---- 开盘时刻：执行昨日收盘确认的信号 ----
        if pending_entry and entry_i is None:
            gap_ok = last_entry_index is None or (i - last_entry_index) >= window_days
            if gap_ok:
                entry_i = i
                entry_price = open_[i] * (1.0 + cost)
                highest_close = close[i]
                last_entry_index = i
                atr_here = atr[i]
                if stop_multiple_atr is not None and atr_here:
                    stop_level = entry_price - stop_multiple_atr * atr_here
                else:
                    stop_level = None
                if trail_multiple_atr is not None and atr_here:
                    trail_level = highest_close - trail_multiple_atr * atr_here
                else:
                    trail_level = None
            pending_entry = False
        elif pending_exit and entry_i is not None:
            close_trade(i, open_[i] * (1.0 - cost), "signal")
            pending_exit = False
        else:
            pending_entry = False
            pending_exit = False

        # ---- 盘中：ATR 止损 / 移动止盈检查（用截至昨日的水平） ----
        if entry_i is not None and i > entry_i:
            exit_price: Optional[float] = None
            if stop_level is not None and low[i] <= stop_level:
                exit_price = min(open_[i], stop_level)
                reason = "stop"
            elif trail_level is not None and low[i] <= trail_level:
                exit_price = min(open_[i], trail_level)
                reason = "trail"
            if exit_price is not None:
                close_trade(i, exit_price * (1.0 - cost), reason)
                stop_level = None
                trail_level = None

        # ---- 收盘时刻：更新权益曲线与信号 ----
        if entry_i is not None:
            holding_bars += 1
            highest_close = max(highest_close, close[i])
            if trail_multiple_atr is not None:
                atr_here = atr[entry_i]
                if atr_here:
                    trail_level = highest_close - trail_multiple_atr * atr_here
            equity[offset] = realized * (close[i] / entry_price)
            if sell_signal[i] is not None:
                pending_exit = True
        else:
            equity[offset] = realized
            if buy_signal[i] is not None:
                allowed = True
                if use_trend_filter:
                    sma_today = sma200[i]
                    sma_prev = sma200[i - 1] if i >= 1 else None
                    allowed = (
                        sma_today is not None
                        and sma_prev is not None
                        and close[i] > sma_today
                        and sma_today > sma_prev
                    )
                if allowed and use_volume_filter:
                    vol_ref = vol_sma20[i]
                    allowed = vol_ref is not None and volume[i] > vol_ref
                if allowed:
                    pending_entry = True

    if entry_i is not None:
        close_trade(end_index, close[end_index] * (1.0 - cost), "segment_end")

    return {
        "trades": trades,
        "equity": equity,
        "holding_bars": holding_bars,
    }


def simulate_buy_hold(
    base: Dict[str, Any],
    start_index: int,
    end_index: int,
    cost_pct_per_side: float = DEFAULT_COST_PCT_PER_SIDE,
) -> Dict[str, Any]:
    """窗口起点开盘买入、终点收盘卖出的买入持有基准。

    输出结构与 simulate_trades 一致（恰好一笔交易），可直接交给
    summarize_metrics 计算同口径绩效。
    """
    close: List[float] = base["close"]
    open_: List[float] = base["open"]
    dates: List[str] = base["dates"]
    cost = cost_pct_per_side / 100.0
    entry_price = open_[start_index] * (1.0 + cost)
    net_exit = close[end_index] * (1.0 - cost)
    trade_return = (net_exit / entry_price - 1.0) * 100.0 if entry_price > 0 else 0.0
    equity = (
        [close[i] / entry_price for i in range(start_index, end_index + 1)]
        if entry_price > 0 else [1.0] * (end_index - start_index + 1)
    )
    return {
        "trades": [{
            "entry_date": dates[start_index],
            "exit_date": dates[end_index],
            "entry_price": round(entry_price, 4),
            "exit_price": round(net_exit, 4),
            "return_pct": round(trade_return, 4),
            "bars_held": end_index - start_index,
            "exit_reason": "buy_hold",
        }],
        "equity": equity,
        "holding_bars": len(equity),
    }


def timing_signals_from_trades(
    base: Dict[str, Any],
    trade_pairs: Sequence[Tuple[str, str]],
) -> Dict[str, List[Any]]:
    """把已确认的 (entry_date, exit_date) 时点转换为“次日开盘成交”合成信号。

    用于基准对比：在另一条价格序列上原样重放策略的每笔买卖时点。
    信号放在成交 bar 的前一根 bar 收盘（与 simulate_trades 的执行假设
    一致）；成交日映射不到时取目标序列首个不早于该日的 bar，重放时
    配合 window_days=1 使用以跳过间隔限制。
    """
    n = base["n"]
    dates: List[str] = base["dates"]
    close: List[float] = base["close"]
    buy_signal: List[Optional[float]] = [None] * n
    sell_signal: List[Optional[float]] = [None] * n

    def locate(wanted: str) -> Optional[int]:
        pos = bisect_left(dates, wanted)
        return pos if pos < n else None

    for entry_date, exit_date in trade_pairs:
        entry_i = locate(entry_date)
        exit_i = locate(exit_date)
        if entry_i is None or exit_i is None or exit_i < entry_i:
            continue
        buy_at = max(entry_i - 1, 0)
        buy_signal[buy_at] = close[buy_at]
        # exit_i == entry_i 时退而求其次：入场 bar 收盘给卖出信号，次日开盘离场
        sell_at = max(exit_i - 1, entry_i)
        sell_signal[sell_at] = close[sell_at]
    return {"buy_signal": buy_signal, "sell_signal": sell_signal}


def summarize_metrics(
    simulation: Dict[str, Any],
    start_index: int,
    end_index: int,
    short_term_tax_pct: float = DEFAULT_SHORT_TERM_TAX_PCT,
    long_term_tax_pct: float = DEFAULT_LONG_TERM_TAX_PCT,
) -> Dict[str, Any]:
    """由模拟结果计算绩效指标（含按美国资本利得税近似的税后收益）。

    税率按持仓时长区分：持有满约一年按长期税率，否则按短期税率。
    """
    equity: List[float] = simulation["equity"]
    trades: List[Dict[str, Any]] = simulation["trades"]
    seg_len = len(equity)
    years = seg_len / TRADING_DAYS_PER_YEAR if seg_len else 0.0

    total_return = (equity[-1] / equity[0] - 1.0) * 100.0 if equity else 0.0
    cagr = 0.0
    if years > 0 and equity[0] > 0 and equity[-1] > 0:
        cagr = (math.pow(equity[-1] / equity[0], 1.0 / years) - 1.0) * 100.0

    max_dd = 0.0
    peak = equity[0] if equity else 1.0
    daily_returns: List[float] = []
    prev = equity[0] if equity else 1.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            max_dd = min(max_dd, value / peak - 1.0)
        if prev > 0:
            daily_returns.append(value / prev - 1.0)
        prev = value

    sharpe = 0.0
    sortino = 0.0
    if daily_returns:
        mean_r = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)
        std_r = math.sqrt(variance)
        downside = [min(r, 0.0) for r in daily_returns]
        down_var = sum(r ** 2 for r in downside) / len(downside)
        down_std = math.sqrt(down_var)
        if std_r > 0:
            sharpe = mean_r / std_r * math.sqrt(TRADING_DAYS_PER_YEAR)
        if down_std > 0:
            sortino = mean_r / down_std * math.sqrt(TRADING_DAYS_PER_YEAR)

    gross_profit = sum(t["return_pct"] for t in trades if t["return_pct"] > 0)
    gross_loss = sum(t["return_pct"] for t in trades if t["return_pct"] < 0)
    wins = [t for t in trades if t["return_pct"] > 0]
    profit_factor: Optional[float]
    if gross_loss < 0:
        profit_factor = round(gross_profit / abs(gross_loss), 4)
    elif gross_profit > 0:
        profit_factor = 99.0  # 无亏损交易时封顶展示
    else:
        profit_factor = 0.0

    avg_trade = (
        sum(t["return_pct"] for t in trades) / len(trades) if trades else 0.0
    )
    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
    avg_holding = (
        sum(t["bars_held"] for t in trades) / len(trades) if trades else 0.0
    )
    exposure = (
        simulation["holding_bars"] / seg_len * 100.0 if seg_len else 0.0
    )

    # 税后收益：对每笔正收益按美国资本利得税计税（亏损不抵扣），逐笔复利；
    # 持有满约一年（LONG_TERM_HOLDING_BARS）适用长期税率，否则适用短期税率。
    short_rate = _clamp(float(short_term_tax_pct), 0.0, 100.0) / 100.0
    long_rate = _clamp(float(long_term_tax_pct), 0.0, 100.0) / 100.0
    after_tax_mult = 1.0
    for trade in trades:
        trade_r = trade["return_pct"] / 100.0
        rate = (
            long_rate if trade["bars_held"] >= LONG_TERM_HOLDING_BARS else short_rate
        )
        after_tax_mult *= 1.0 + trade_r - max(trade_r, 0.0) * rate
    after_tax_total = (after_tax_mult - 1.0) * 100.0
    after_tax_cagr = 0.0
    if years > 0 and after_tax_mult > 0:
        after_tax_cagr = (math.pow(after_tax_mult, 1.0 / years) - 1.0) * 100.0

    return {
        "total_return_pct": round(total_return, 4),
        "cagr_pct": round(cagr, 4),
        "after_tax_total_return_pct": round(after_tax_total, 4),
        "after_tax_cagr_pct": round(after_tax_cagr, 4),
        "max_drawdown_pct": round(max_dd * 100.0, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "profit_factor": profit_factor,
        "trades": len(trades),
        "win_rate_pct": round(win_rate, 4),
        "avg_trade_pct": round(avg_trade, 4),
        "avg_holding_days": round(avg_holding, 2),
        "exposure_pct": round(exposure, 4),
        "trades_per_year": round(len(trades) / years, 4) if years > 0 else 0.0,
    }


def objective_score(metrics: Dict[str, Any], segment_years: float) -> float:
    """平衡型目标函数：不以最大化历史收益为唯一目标。

    组成（权重和约为 1）：
    - 风险调整收益：Sharpe 0.28 + Sortino 0.12
    - 收益：CAGR 0.20（25% 年化封顶）、平均单笔 0.10（5% 封顶）
    - 交易质量：盈亏比 0.15（PF 2.5 封顶）、胜率 0.10（50% 居中）
    - 回撤惩罚：最大回撤绝对值 × 0.60
    - 频率项：偏好每年约 4 笔交易，过密或过疏都轻微扣分
    - 交易次数低于 min_trades 时直接判为不合格（避免靠极少量运气交易取胜）
    """
    min_trades = max(3, int(round(segment_years)))
    trades = metrics["trades"]
    if trades < min_trades:
        return -1.0e6 + float(trades)

    dd_frac = abs(metrics["max_drawdown_pct"]) / 100.0
    sharpe_term = _clamp(float(metrics["sharpe"]), -3.0, 3.0)
    sortino_term = _clamp(float(metrics["sortino"]), -3.0, 3.0)
    cagr_term = _clamp(metrics["cagr_pct"] / 25.0, -2.0, 2.0)
    pf = metrics["profit_factor"] if metrics["profit_factor"] is not None else 0.0
    pf_term = _clamp(pf - 1.0, -1.0, 1.5)
    win_term = metrics["win_rate_pct"] / 100.0 - 0.5
    avg_trade_term = _clamp(metrics["avg_trade_pct"] / 5.0, -2.0, 2.0)
    freq_term = -abs(_clamp(metrics["trades_per_year"], 0.0, 12.0) - 4.0) / 8.0

    score = (
        0.28 * sharpe_term
        + 0.12 * sortino_term
        + 0.20 * cagr_term
        + 0.15 * pf_term
        + 0.10 * win_term
        + 0.10 * avg_trade_term
        + freq_term
        - 0.60 * dd_frac
    )
    return score
