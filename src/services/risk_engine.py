# -*- coding: utf-8 -*-
"""
风险引擎（RiskEngine）：仓位测算与上限约束
========================================

本模块只做计算，不下单、不持有仓位：

- 输入：组合价值、现仓、计划入场价、止损价、ATR、单笔风险、
  个股/行业/组合上限；
- 输出：``ExecutionPlan``（建议股数、建议金额、组合风险占比、
  拒绝原因）。

基础规则（固定收益风险模型）：

    risk_dollars = portfolio_value * risk_per_trade
    shares = risk_dollars / (sizing_price - stop_price)

其中 sizing_price 使用 maximum_entry（如提供），否则使用 entry_reference。

再依次应用：个股上限、行业上限、组合总敞口上限。
止损距离为零或非法时拒绝（不允许无限杠杆）。
"""

from __future__ import annotations

from math import isfinite
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

REASON_OK = "OK"
REASON_INVALID_STOP_DISTANCE = "INVALID_STOP_DISTANCE"
REASON_INVALID_INPUT = "INVALID_INPUT"
REASON_SINGLE_STOCK_CAP = "SINGLE_STOCK_CAP"
REASON_SECTOR_CAP = "SECTOR_CAP"
REASON_PORTFOLIO_CAP = "PORTFOLIO_CAP"


@dataclass(frozen=True)
class ExecutionPlan:
    """风险引擎输出的执行计划（建议性质，不直接下单）。"""

    ticker: str
    action: str
    approved: bool
    reason: str
    entry_reference: Optional[float] = None
    maximum_entry: Optional[float] = None
    stop: Optional[float] = None
    risk_per_share: Optional[float] = None
    suggested_shares: int = 0
    suggested_position_value: float = 0.0
    portfolio_risk_pct: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


def _positive(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if isinstance(value, bool) or not isfinite(number) or number <= 0:
        return None
    return number


def build_execution_plan(
    *,
    ticker: str,
    action: str = "BUY",
    portfolio_value: Any,
    entry_reference: Any,
    stop_price: Any,
    risk_per_trade: float = 0.01,
    maximum_entry: Optional[float] = None,
    max_single_stock_pct: float = 0.20,
    sector: Optional[str] = None,
    sector_positions_value: float = 0.0,
    max_sector_pct: float = 0.35,
    current_positions_value: float = 0.0,
    max_total_exposure_pct: float = 0.90,
    current_ticker_position_value: float = 0.0,
) -> ExecutionPlan:
    """按固定风险模型与三层上限生成执行计划。"""
    portfolio = _positive(portfolio_value)
    entry = _positive(entry_reference)
    if portfolio is None or entry is None:
        return ExecutionPlan(
            ticker=ticker, action=action, approved=False,
            reason=REASON_INVALID_INPUT, entry_reference=None,
        )
    fractions = (risk_per_trade, max_single_stock_pct, max_sector_pct, max_total_exposure_pct)
    exposures = (sector_positions_value, current_positions_value, current_ticker_position_value)

    def valid_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)

    if (action != "BUY" or any(not valid_number(v) or not 0 <= v <= 1 for v in fractions)
            or any(not valid_number(v) or v < 0 for v in exposures)
            or (maximum_entry is not None and (not valid_number(maximum_entry) or maximum_entry < entry))):
        return ExecutionPlan(ticker=ticker, action=action, approved=False, reason=REASON_INVALID_INPUT)
    sizing_price = float(maximum_entry) if maximum_entry is not None else entry
    stop = _positive(stop_price)
    risk_distance = sizing_price - stop if stop is not None and stop < entry else None
    if risk_distance is None or not risk_distance > 0:
        return ExecutionPlan(
            ticker=ticker, action=action, approved=False,
            reason=REASON_INVALID_STOP_DISTANCE,
            entry_reference=entry, maximum_entry=maximum_entry, stop=stop,
        )

    risk_dollars = portfolio * max(0.0, float(risk_per_trade))
    raw_shares = int(risk_dollars // risk_distance)
    if raw_shares <= 0:
        return ExecutionPlan(
            ticker=ticker, action=action, approved=False,
            reason=REASON_INVALID_INPUT, entry_reference=entry,
            maximum_entry=maximum_entry, stop=stop,
            risk_per_share=risk_distance,
            details={"hint": "单笔风险金额不足以买入 1 股"},
        )

    # 三层上限（按“新增后”口径逐项收紧，任一超限即拒绝并给出原因）。
    shares = raw_shares
    single_cap_value = portfolio * max_single_stock_pct
    if shares * sizing_price + current_ticker_position_value > single_cap_value:
        affordable = int((single_cap_value - current_ticker_position_value) // sizing_price)
        if affordable <= 0:
            return _rejected(
                ticker, action, entry, maximum_entry, stop, risk_distance,
                REASON_SINGLE_STOCK_CAP, raw_shares,
            )
        shares = min(shares, affordable)
    if sector is not None:
        sector_cap_value = portfolio * max_sector_pct
        if shares * sizing_price + sector_positions_value > sector_cap_value:
            affordable = int((sector_cap_value - sector_positions_value) // sizing_price)
            if affordable <= 0:
                return _rejected(
                    ticker, action, entry, maximum_entry, stop, risk_distance,
                    REASON_SECTOR_CAP, raw_shares,
                )
            shares = min(shares, affordable)
    total_cap_value = portfolio * max_total_exposure_pct
    if shares * sizing_price + current_positions_value > total_cap_value:
        affordable = int((total_cap_value - current_positions_value) // sizing_price)
        if affordable <= 0:
            return _rejected(
                ticker, action, entry, maximum_entry, stop, risk_distance,
                REASON_PORTFOLIO_CAP, raw_shares,
            )
        shares = min(shares, affordable)

    position_value = shares * sizing_price
    return ExecutionPlan(
        ticker=ticker,
        action=action,
        approved=True,
        reason=REASON_OK,
        entry_reference=entry,
        maximum_entry=maximum_entry,
        stop=stop,
        risk_per_share=risk_distance,
        suggested_shares=shares,
        suggested_position_value=round(position_value, 2),
        portfolio_risk_pct=round(shares * risk_distance / portfolio * 100.0, 4),
        details={
            "sizing_price": sizing_price,
            "raw_shares": raw_shares,
            "risk_dollars": round(risk_dollars, 2),
        },
    )


def _rejected(ticker, action, entry, maximum_entry, stop, risk_distance, reason, raw_shares):
    return ExecutionPlan(
        ticker=ticker,
        action=action,
        approved=False,
        reason=reason,
        entry_reference=entry,
        maximum_entry=maximum_entry,
        stop=stop,
        risk_per_share=risk_distance,
        details={"raw_shares": raw_shares},
    )


def current_exposure_pct(
    positions: Mapping[str, float],
    portfolio_value: Any,
) -> float:
    """当前组合总敞口占比（%）。"""
    portfolio = _positive(portfolio_value)
    if portfolio is None:
        return 0.0
    return round(sum(max(0.0, float(v)) for v in positions.values()) / portfolio * 100.0, 4)
