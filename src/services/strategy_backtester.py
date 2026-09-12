# -*- coding: utf-8 -*-
"""
策略回测引擎（Auto Tune 专用）
================================

为技术指标图 "Auto Tune" 提供确定性的历史回测：

1. `prepare_base_series`（位于 strategy_engine）一次性计算与阈值无关的
   基础指标序列（公式与 indicator_service 完全一致，复用其
   SMA/EMA/滚动窗口函数）。
2. `compute_composite_signals` 委托 strategy_engine 的共享评分实现
   （MACD 滚动百分位 + KDJ 反转 + RSI 反转 + 趋势 regime +
   价格动量改善/恶化 + 扩展因子 BOLL/CCI/DMI/MFI/量能/52 周位置），
   结果与 compute_indicators 一致。
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
from bisect import bisect_left
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.services.strategy_engine import (
    evaluate_signals,
    prepare_base_series,  # noqa: F401 兼容性重新导出：optimizer/测试仍从本模块导入
)
from src.services.execution_policy import DECISION_EXECUTE, evaluate_entry
from src.services.allocation import PortfolioEnvironment

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


def compute_composite_signals(
    base: Dict[str, Any],
    thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, List[Any]]:
    """按 indicator_service 复合评分逻辑计算 BUY/SELL 信号。

    本函数是兼容性入口：评分公式的唯一实现位于
    strategy_engine.evaluate_signals（经 score_bar 逐 bar 决策），
    此处仅做委托并保持历史返回结构（分数 + 触发信号）不变。
    """
    result = evaluate_signals(base, thresholds)
    return {
        "buy_score": result["buy_score"],
        "buy_allocation": result["buy_allocation"],
        "sell_score": result["sell_score"],
        "buy_signal": result["buy_signal"],
        "sell_signal": result["sell_signal"],
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
    max_entry_gap_atr: Optional[float] = None,
    size_by_score: bool = False,
    min_trade_gap_bars: int = 0,
) -> Dict[str, Any]:
    """在 [start_index, end_index] 区间内模拟交易（其余参数见模块 docstring）。

    执行假设：
    - 信号在收盘确认，次日开盘价成交（无同日收盘执行）。
    - 两次买入之间至少间隔 window_days 根交易日（默认 90，即最多约
      一个季度一次往返）。
    - ATR 止损/移动止盈用入场前一根已收盘 bar 的 ATR(14)；初始止损
      从入场当天生效，盘中跌破按止损价成交，跳空低开按开盘价成交。
      移动止盈以持仓期间最高收盘价为基准，从下一根 bar 生效。
    - 间隙保护（可选，与实盘共用 execution_policy.evaluate_entry）：
      ``max_entry_gap_atr`` 为 None 时关闭（保持历史行为）；启用后
      次日开盘高于 ``信号收盘 + 倍数 * ATR`` 即跳过本次入场并记入
      ``skipped_entries``（跳过不计入建仓间隔锁定）。
    - 区间结束时仍持仓则按区间最后收盘价强制平仓。
    - 初始资金为 1，equity 每根 bar 一个收盘权益点，最后一点含平仓成本。
      holding_bars 累计有盘中持仓的 bar（开盘即平仓的 bar 不计入）。
    - size_by_score 启用后按信号的 buy_allocation 分配权益；剩余现金不参与涨跌，
      单仓不加仓、不借款。min_trade_gap_bars 限制普通买卖，保护性退出不受限。
      decisions 中预算百分比均相对初始资金，卖出金额为扣费后现金流。
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
    allocations = signals.get("buy_allocation", [1.0] * len(close))
    scores = {side: signals.get(f"{side}_score", [None] * len(close)) for side in ("buy", "sell")}

    cost = cost_pct_per_side / 100.0
    environment = PortfolioEnvironment(cost)
    trades: List[Dict[str, Any]] = []
    skipped_entries: List[Dict[str, Any]] = []
    equity = [1.0] * (end_index - start_index + 1)
    realized = 1.0
    cash = 1.0
    units = 0.0
    allocation = 1.0
    last_trade_index: Optional[int] = None
    decisions: List[Dict[str, Any]] = []
    pending_decision: Optional[Dict[str, Any]] = None
    holding_bars = 0
    entry_i: Optional[int] = None
    entry_price = 0.0
    stop_level: Optional[float] = None
    trail_level: Optional[float] = None
    entry_atr: Optional[float] = None
    highest_close = 0.0
    last_entry_index: Optional[int] = None

    def execution_fields(fill):
        return dict(execution_price=fill.after.last_price,
                    holding_pct=fill.after.current_exposure * 100,
                    trade_nav_pct=abs(fill.trade_value) / fill.before.nav * 100)

    def close_trade(exit_i: int, exit_price: float, reason: str):
        nonlocal entry_i, realized, cash, units, last_trade_index
        assert entry_i is not None
        # 所有调用方传入未扣费成交价；平仓费用只在这里收取一次。
        closed = environment.rebalance(0, exit_price)
        net_exit = (-closed.trade_value - closed.transaction_cost) / closed.before.shares
        trade_return = (net_exit / entry_price - 1.0) * 100.0
        trades.append({
            "entry_date": dates[entry_i],
            "exit_date": dates[exit_i],
            "entry_price": round(entry_price, 4),
            "exit_price": round(net_exit, 4),
            "return_pct": round(trade_return, 4),
            "allocation_pct": allocation * 100.0,
            "profit": closed.realized_profit,
            "bars_held": exit_i - entry_i,
            "exit_reason": reason,
        })
        cash = environment.cash
        realized = cash
        units = 0.0
        last_trade_index = exit_i
        entry_i = None
        return closed

    pending_entry = False
    pending_exit = False
    for i in range(start_index, end_index + 1):
        offset = i - start_index

        # ---- 开盘时刻：执行昨日收盘确认的信号 ----
        if pending_entry and entry_i is None:
            gap_ok = last_entry_index is None or (i - last_entry_index) >= window_days
            if gap_ok:
                entry_atr = atr[i - 1] if i > 0 else None
                verdict = evaluate_entry(
                    signal_close=close[i - 1] if i > 0 else open_[i],
                    next_open=open_[i],
                    atr=entry_atr,
                    max_entry_gap_atr=max_entry_gap_atr,
                )
                if verdict["decision"] != DECISION_EXECUTE:
                    if pending_decision is not None:
                        pending_decision["reason"] = verdict["reason"]
                    skipped_entries.append({
                        "signal_date": dates[i - 1] if i > 0 else dates[i],
                        "date": dates[i],
                        "reason": verdict["reason"],
                        "signal_close": verdict["signal_close"],
                        "next_open": verdict["expected_execution"],
                        "maximum_entry": verdict["maximum_entry"],
                    })
                    entry_atr = None
                else:
                    entry_i = i
                    allocation = _clamp(allocations[i - 1], 0.0, 1.0) if size_by_score else 1.0
                    entered = environment.rebalance(environment.target_for_budget_fraction(allocation), open_[i])
                    entry_price = environment.average_cost
                    spend = entered.before.cash - entered.after.cash
                    units = environment.shares
                    cash = environment.cash
                    last_trade_index = i
                    if pending_decision is not None:
                        pending_decision.update(status="executed", reason="signal", date=dates[i],
                                                executed_budget_pct=spend * 100.0, cash_after_pct=cash * 100.0,
                                                **execution_fields(entered))
                    highest_close = 0.0
                    last_entry_index = i
                    if stop_multiple_atr is not None and entry_atr:
                        stop_level = entry_price - stop_multiple_atr * entry_atr
                    else:
                        stop_level = None
                    trail_level = None
            pending_entry = False
        elif pending_exit and entry_i is not None:
            proceeds = units * open_[i] * (1.0 - cost)
            closed = close_trade(i, open_[i], "signal")
            if pending_decision is not None:
                pending_decision.update(status="executed", reason="signal", date=dates[i],
                                        executed_budget_pct=proceeds * 100.0, cash_after_pct=cash * 100.0,
                                        **execution_fields(closed))
            pending_exit = False
        else:
            pending_entry = False
            pending_exit = False

        # ---- 盘中：ATR 止损 / 移动止盈检查（用截至昨日的水平） ----
        if entry_i is not None:
            # 多头从上方触及退出价，取最高的有效水平；不能越过较高的
            # 移动止盈后再按更低的固定止损成交。
            exit_level = stop_level
            reason = "stop"
            if trail_level is not None and (exit_level is None or trail_level > exit_level):
                exit_level = trail_level
                reason = "trail"
            if exit_level is not None and low[i] <= exit_level:
                # 旧持仓跳空至退出价以下时开盘即平仓；其余退出 bar 有盘中敞口。
                if i == entry_i or open_[i] > exit_level:
                    holding_bars += 1
                proceeds = units * min(open_[i], exit_level) * (1.0 - cost)
                closed = close_trade(i, min(open_[i], exit_level), reason)
                decisions.append(dict(signal_date=dates[i], date=dates[i], side="sell", status="executed",
                                      reason=reason, score=None, suggested_budget_pct=proceeds * 100.0,
                                      executed_budget_pct=proceeds * 100.0, cash_after_pct=cash * 100.0,
                                      **execution_fields(closed)))
                stop_level = None
                trail_level = None
            else:
                holding_bars += 1

        # ---- 收盘时刻：更新权益曲线与信号 ----
        if entry_i is not None:
            highest_close = max(highest_close, close[i])
            if trail_multiple_atr is not None and entry_atr:
                trail_level = highest_close - trail_multiple_atr * entry_atr
            equity[offset] = environment.mark_to_market(close[i]).nav
        else:
            equity[offset] = realized
        pending_decision = None
        for side, trigger in (("sell", sell_signal[i]), ("buy", buy_signal[i])):
            if trigger is not None:
                fraction = _clamp(allocations[i], 0.0, 1.0) if size_by_score else 1.0
                suggested = equity[offset] * fraction if side == "buy" else units * close[i]
                decision = dict(signal_date=dates[i], date=dates[i], side=side, status="skipped",
                                reason="signal", score=scores[side][i],
                                holding_pct=environment.mark_to_market(close[i]).current_exposure * 100,
                                suggested_budget_pct=suggested * 100.0,
                                executed_budget_pct=0.0, cash_after_pct=cash * 100.0)
                decisions.append(decision)
                if side == "buy" and cash <= 1e-12:
                    decision["reason"] = "no_cash"
                    continue
                if side == "buy" and entry_i is not None:
                    decision["reason"] = "position_open"
                    continue
                if side == "sell" and entry_i is None:
                    decision["reason"] = "no_position"
                    continue
                if i == end_index:
                    decision["reason"] = "no_next_bar"
                    continue
                if last_trade_index is not None and i + 1 - last_trade_index < min_trade_gap_bars:
                    decision["reason"] = "trade_cooldown"
                    continue
                if side == "buy" and last_entry_index is not None and i + 1 - last_entry_index < window_days:
                    decision["reason"] = "entry_cooldown"
                    continue
                if side == "sell":
                    pending_exit = True
                    pending_decision = decision
                    continue
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
                    pending_decision = decision
                else:
                    decision["reason"] = "entry_filter"

    if entry_i is not None:
        proceeds = units * close[end_index] * (1.0 - cost)
        closed = close_trade(end_index, close[end_index], "segment_end")
        equity[-1] = realized
        decisions.append(dict(signal_date=dates[end_index], date=dates[end_index], side="sell",
                              status="executed", reason="segment_end", score=None, suggested_budget_pct=proceeds * 100.0,
                              executed_budget_pct=proceeds * 100.0, cash_after_pct=cash * 100.0,
                              **execution_fields(closed)))

    return {
        "trades": trades,
        "decisions": decisions,
        "skipped_entries": skipped_entries,
        "equity": equity,
        "holding_bars": holding_bars,
        "initial_equity": 1.0,
    }


def simulate_buy_hold(
    base: Dict[str, Any],
    start_index: int,
    end_index: int,
    cost_pct_per_side: float = DEFAULT_COST_PCT_PER_SIDE,
) -> Dict[str, Any]:
    """窗口起点开盘买入、终点收盘卖出的买入持有基准。

    输出结构与 simulate_trades 一致（恰好一笔交易），初始资金为 1，
    最后一个权益点为扣除平仓费后的现金，可直接交给 summarize_metrics。
    """
    close: List[float] = base["close"]
    open_: List[float] = base["open"]
    dates: List[str] = base["dates"]
    cost = cost_pct_per_side / 100.0
    environment = PortfolioEnvironment(cost)
    environment.rebalance(1.0, open_[start_index])
    entry_price = environment.average_cost
    equity = [environment.mark_to_market(close[i]).nav for i in range(start_index, end_index + 1)]
    exited = environment.rebalance(0.0, close[end_index])
    net_exit = (-exited.trade_value - exited.transaction_cost) / exited.before.shares
    trade_return = (net_exit / entry_price - 1.0) * 100.0
    equity[-1] = environment.snapshot.nav
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
        "initial_equity": 1.0,
        "transaction_cost": environment.total_transaction_cost,
        "turnover": environment.turnover,
        "trade_count": environment.trade_count,
        "average_exposure": 1.0,
    }


def timing_signals_from_trades(
    base: Dict[str, Any],
    trade_pairs: Sequence[Tuple[str, str]],
    allocations: Optional[Sequence[float]] = None,
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
    buy_allocation = [1.0] * n

    def locate(wanted: str) -> Optional[int]:
        pos = bisect_left(dates, wanted)
        return pos if pos < n else None

    for trade_index, (entry_date, exit_date) in enumerate(trade_pairs):
        entry_i = locate(entry_date)
        exit_i = locate(exit_date)
        if entry_i is None or exit_i is None or exit_i < entry_i:
            continue
        buy_at = max(entry_i - 1, 0)
        buy_signal[buy_at] = close[buy_at]
        if allocations is not None:
            buy_allocation[buy_at] = allocations[trade_index]
        # exit_i == entry_i 时退而求其次：入场 bar 收盘给卖出信号，次日开盘离场
        sell_at = max(exit_i - 1, entry_i)
        sell_signal[sell_at] = close[sell_at]
    return {"buy_signal": buy_signal, "sell_signal": sell_signal, "buy_allocation": buy_allocation}


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
    initial_equity = float(simulation.get("initial_equity", 1.0))

    total_return = (equity[-1] / initial_equity - 1.0) * 100.0 if equity else 0.0
    cagr = 0.0
    if years > 0 and initial_equity > 0 and equity[-1] > 0:
        cagr = (math.pow(equity[-1] / initial_equity, 1.0 / years) - 1.0) * 100.0

    max_dd = 0.0
    peak = initial_equity
    daily_returns: List[float] = []
    prev = initial_equity
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

    # Sized trades contribute their cash P&L, not an unweighted sum of returns.
    trade_profits = [t.get("profit", t["return_pct"]) for t in trades]
    gross_profit = sum(profit for profit in trade_profits if profit > 0)
    gross_loss = sum(profit for profit in trade_profits if profit < 0)
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
        trade_r = trade["return_pct"] / 100.0 * trade.get("allocation_pct", 100.0) / 100.0
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

    组成：
    - 风险调整收益：Sharpe 0.60（限制在 -3 至 3）
    - 成本后收益：CAGR / 25% × 0.40（归一化项限制在 -2 至 2）
    - 回撤惩罚：最大回撤绝对值 × 0.60
    - 不再重复奖励 Sortino / 盈亏比 / 胜率 / 单笔收益等相关指标
    - 不设偏好交易频率：换手成本已在成交和权益中计入，避免重复扣费
    - 交易次数低于 min_trades 时直接判为不合格（避免靠极少量运气交易取胜）
    """
    min_trades = max(3, int(round(segment_years)))
    trades = metrics["trades"]
    if trades < min_trades:
        return -1.0e6 + float(trades)

    dd_frac = abs(metrics["max_drawdown_pct"]) / 100.0
    sharpe_term = _clamp(float(metrics["sharpe"]), -3.0, 3.0)
    cagr_term = _clamp(metrics["cagr_pct"] / 25.0, -2.0, 2.0)

    score = (
        0.60 * sharpe_term
        + 0.40 * cagr_term
        - 0.60 * dd_frac
    )
    return score
