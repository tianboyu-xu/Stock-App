# -*- coding: utf-8 -*-
"""
执行政策（ExecutionPolicy）：回测与实盘共用的成交假设
====================================================

基准模型（与回测历史行为一致）：

- 信号由 finalized 的 T 日收盘确认；
- 在 T+1 常规时段开盘价成交（``expected_execution = next open``）。

间隙保护（gap / no-chase）：

- ``maximum_entry_gap_atr`` 为 None 时关闭间隙规则（保持历史回测行为）。
- 启用时：``maximum_entry = signal_close + max_entry_gap_atr * ATR``，
  边界（含等于）执行，超出则 ``SKIP / GAP_TOO_LARGE``；
  向下跳空属有利成交，不受限制。
- 启用规则但 ATR 缺失时 fail-closed：``SKIP / NO_ATR_DATA``。
- 信号只在紧随信号 bar 的下一个常规时段有效，过期
  ``SKIP / SIGNAL_EXPIRED``。

回测（``simulate_trades``）与实盘（信号任务）必须使用同一函数：
``evaluate_entry``。任何只上一边、另一边没有的规则都是缺陷。
"""

from __future__ import annotations

from math import isfinite
from typing import Any, Dict, Optional

DECISION_EXECUTE = "EXECUTE"
DECISION_SKIP = "SKIP"

REASON_OK = "OK"
REASON_GAP_TOO_LARGE = "GAP_TOO_LARGE"
REASON_SIGNAL_EXPIRED = "SIGNAL_EXPIRED"
REASON_NO_ATR_DATA = "NO_ATR_DATA"


def evaluate_entry(
    *,
    signal_close: float,
    next_open: float,
    atr: Optional[float] = None,
    max_entry_gap_atr: Optional[float] = None,
    signal_expired: bool = False,
) -> Dict[str, Any]:
    """判定一次计划入场是否执行（回测与实盘共用）。

    Args:
        signal_close: 信号 bar（T 日）收盘价。
        next_open: T+1 开盘价（计划成交价）。
        atr: 入场前一根已收盘 bar 的 ATR(14)；间隙规则启用时必需。
        max_entry_gap_atr: 允许的最大上跳间隙（ATR 倍数）；None = 关闭规则。
        signal_expired: 信号是否已过期（错过紧随的下一个常规时段）。

    Returns:
        {
            "decision": "EXECUTE" | "SKIP",
            "reason": "OK" | "GAP_TOO_LARGE" | "SIGNAL_EXPIRED" | "NO_ATR_DATA",
            "expected_execution": next_open,
            "maximum_entry": 上限价或 None（规则关闭时）,
            "signal_close": ...,
        }
    """
    def invalid(reason):
        return {"decision": DECISION_SKIP, "reason": reason,
                "expected_execution": next_open, "maximum_entry": None,
                "signal_close": signal_close}

    def finite(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)

    if not finite(signal_close) or not finite(next_open) or min(signal_close, next_open) <= 0:
        return invalid("INVALID_PRICE")
    if max_entry_gap_atr is not None and (not finite(max_entry_gap_atr) or max_entry_gap_atr < 0):
        return invalid("INVALID_GAP_LIMIT")
    if signal_expired:
        return {
            "decision": DECISION_SKIP,
            "reason": REASON_SIGNAL_EXPIRED,
            "expected_execution": next_open,
            "maximum_entry": None,
            "signal_close": signal_close,
        }
    maximum_entry: Optional[float] = None
    if max_entry_gap_atr is not None:
        if not finite(atr) or not atr > 0:
            return {
                "decision": DECISION_SKIP,
                "reason": REASON_NO_ATR_DATA,
                "expected_execution": next_open,
                "maximum_entry": None,
                "signal_close": signal_close,
            }
        maximum_entry = signal_close + float(max_entry_gap_atr) * atr
        if not isfinite(maximum_entry):
            return invalid("INVALID_GAP_LIMIT")
        if next_open > maximum_entry:
            return {
                "decision": DECISION_SKIP,
                "reason": REASON_GAP_TOO_LARGE,
                "expected_execution": next_open,
                "maximum_entry": maximum_entry,
                "signal_close": signal_close,
            }
    return {
        "decision": DECISION_EXECUTE,
        "reason": REASON_OK,
        "expected_execution": next_open,
        "maximum_entry": maximum_entry,
        "signal_close": signal_close,
    }
