# -*- coding: utf-8 -*-
"""
持仓状态机（Trading State）：策略是否已持有仓位
================================================

简单的 long-only 状态机，与回测“单仓位、无加仓”语义兼容：

    FLAT --BUY--> ENTRY_SIGNALLED --确认执行--> ENTRY_PENDING --确认成交--> LONG
    LONG --SELL--> EXIT_SIGNALLED --确认执行--> EXIT_PENDING --确认成交--> FLAT

- LONG + BUY：忽略，不重复建仓（Rule 9 的仓位层保障）。
- FLAT + SELL：忽略（无仓可平）。
- 状态落库（``strategy_position_states``），应用重启后保持。

本模块只跟踪状态，不做券商下单；执行确认由调用方（纸面/手工）
回填，见 ``confirm_execution`` / ``confirm_fill``。
"""

from __future__ import annotations

from contextlib import closing

from src.repositories.strategy_transactions import begin_strategy_write
from math import isfinite
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

STATE_FLAT = "FLAT"
STATE_ENTRY_SIGNALLED = "ENTRY_SIGNALLED"
STATE_ENTRY_PENDING = "ENTRY_PENDING"
STATE_LONG = "LONG"
STATE_EXIT_SIGNALLED = "EXIT_SIGNALLED"
STATE_EXIT_PENDING = "EXIT_PENDING"

STATES = (
    STATE_FLAT,
    STATE_ENTRY_SIGNALLED,
    STATE_ENTRY_PENDING,
    STATE_LONG,
    STATE_EXIT_SIGNALLED,
    STATE_EXIT_PENDING,
)

# 信号动作 -> 可接受的当前状态（其余组合一律忽略，不抛异常）
_ENTRY_FROM = (STATE_FLAT,)
_EXIT_FROM = (STATE_LONG,)


def _default_session_factory():
    from src.storage import DatabaseManager

    return DatabaseManager.get_instance().get_session()


class TradingStateService:
    """持仓状态机服务（session 由调用方注入，便于测试隔离）。"""

    def __init__(self, session_factory: Optional[Callable[[], Any]] = None) -> None:
        self._session_factory = session_factory or _default_session_factory

    def get_state(
        self,
        ticker: str,
        strategy_id: str,
        strategy_version: str,
        parameter_set_id: str,
    ) -> Dict[str, Any]:
        """查询当前状态（无记录即 FLAT，不落库）。"""
        from src.storage import StrategyPositionStateRecord

        with closing(self._session_factory()) as session:
            row = session.query(StrategyPositionStateRecord).filter_by(
                ticker=_norm(ticker),
                strategy_id=str(strategy_id),
                strategy_version=str(strategy_version),
                parameter_set_id=str(parameter_set_id),
            ).one_or_none()
            if row is None:
                return self._snapshot(None, ticker, strategy_id, strategy_version, parameter_set_id)
            return self._snapshot(row, ticker, strategy_id, strategy_version, parameter_set_id)

    def on_signal(
        self,
        ticker: str,
        strategy_id: str,
        strategy_version: str,
        parameter_set_id: str,
        action: str,
        *,
        signal_id: Optional[str] = None,
        bar_date: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], bool]:
        """消费一个策略信号；返回 (state, accepted)。

        - FLAT + BUY -> ENTRY_SIGNALLED（accepted=True）
        - LONG + SELL -> EXIT_SIGNALLED（accepted=True）
        - 其余组合（LONG+BUY、FLAT+SELL、中间态重复信号）被忽略
          （accepted=False），状态不变。
        """
        normalized_action = str(action or "").strip().upper()
        with closing(self._session_factory()) as session:
            row = self._get_or_create(
                session, ticker, strategy_id, strategy_version, parameter_set_id,
            )
            accepted = False
            if normalized_action == "BUY" and row.state in _ENTRY_FROM:
                row.state = STATE_ENTRY_SIGNALLED
                row.entry_signal_id = signal_id
                row.entry_bar_date = bar_date
                row.exit_signal_id = None
                accepted = True
            elif normalized_action == "SELL" and row.state in _EXIT_FROM:
                row.state = STATE_EXIT_SIGNALLED
                row.exit_signal_id = signal_id
                accepted = True
            row.updated_at = _utcnow()
            session.commit()
            session.refresh(row)
            snapshot = self._snapshot(row, ticker, strategy_id, strategy_version, parameter_set_id)
            return snapshot, accepted

    def confirm_execution(
        self,
        ticker: str,
        strategy_id: str,
        strategy_version: str,
        parameter_set_id: str,
    ) -> Dict[str, Any]:
        """执行已接受（如下单成功/纸面成交计划确认）：SIGNALLED -> PENDING。"""
        return self._transition(
            ticker, strategy_id, strategy_version, parameter_set_id,
            {STATE_ENTRY_SIGNALLED: STATE_ENTRY_PENDING,
             STATE_EXIT_SIGNALLED: STATE_EXIT_PENDING},
        )

    def confirm_fill(
        self,
        ticker: str,
        strategy_id: str,
        strategy_version: str,
        parameter_set_id: str,
        *,
        fill_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """成交已确认：ENTRY_PENDING -> LONG（记录入场价），EXIT_PENDING -> FLAT。"""
        with closing(self._session_factory()) as session:
            row = self._get_or_create(
                session, ticker, strategy_id, strategy_version, parameter_set_id,
            )
            if row.state == STATE_ENTRY_PENDING:
                if (not isinstance(fill_price, (int, float)) or isinstance(fill_price, bool)
                        or not isfinite(fill_price) or fill_price <= 0):
                    raise ValueError("Entry fill requires a finite positive price")
                row.state = STATE_LONG
                row.entry_price = float(fill_price)
            elif row.state == STATE_EXIT_PENDING:
                row.state = STATE_FLAT
                row.entry_signal_id = None
                row.entry_bar_date = None
                row.entry_price = None
                row.exit_signal_id = None
            row.updated_at = _utcnow()
            session.commit()
            session.refresh(row)
            return self._snapshot(row, ticker, strategy_id, strategy_version, parameter_set_id)

    def reset(
        self,
        ticker: str,
        strategy_id: str,
        strategy_version: str,
        parameter_set_id: str,
        *,
        details: Optional[str] = None,
    ) -> Dict[str, Any]:
        """人工复位到 FLAT（对账/异常恢复用）。"""
        with closing(self._session_factory()) as session:
            row = self._get_or_create(
                session, ticker, strategy_id, strategy_version, parameter_set_id,
            )
            row.state = STATE_FLAT
            row.entry_signal_id = None
            row.entry_bar_date = None
            row.entry_price = None
            row.exit_signal_id = None
            row.details = details
            row.updated_at = _utcnow()
            session.commit()
            session.refresh(row)
            return self._snapshot(row, ticker, strategy_id, strategy_version, parameter_set_id)

    # -- internals ------------------------------------------------------

    def _get_or_create(self, session, ticker, strategy_id, strategy_version, parameter_set_id):
        from src.storage import StrategyPositionStateRecord

        begin_strategy_write(session)
        row = session.query(StrategyPositionStateRecord).filter_by(
            ticker=_norm(ticker),
            strategy_id=str(strategy_id),
            strategy_version=str(strategy_version),
            parameter_set_id=str(parameter_set_id),
        ).one_or_none()
        if row is None:
            row = StrategyPositionStateRecord(
                ticker=_norm(ticker),
                strategy_id=str(strategy_id),
                strategy_version=str(strategy_version),
                parameter_set_id=str(parameter_set_id),
                state=STATE_FLAT,
            )
            session.add(row)
            session.flush()
        return row

    def _transition(self, ticker, strategy_id, strategy_version, parameter_set_id, mapping) -> Dict[str, Any]:
        with closing(self._session_factory()) as session:
            row = self._get_or_create(
                session, ticker, strategy_id, strategy_version, parameter_set_id,
            )
            if row.state in mapping:
                row.state = mapping[row.state]
            row.updated_at = _utcnow()
            session.commit()
            session.refresh(row)
            return self._snapshot(row, ticker, strategy_id, strategy_version, parameter_set_id)

    @staticmethod
    def _snapshot(row, ticker, strategy_id, strategy_version, parameter_set_id) -> Dict[str, Any]:
        if row is None:
            return {
                "ticker": _norm(ticker),
                "strategy_id": strategy_id,
                "strategy_version": strategy_version,
                "parameter_set_id": parameter_set_id,
                "state": STATE_FLAT,
                "entry_signal_id": None,
                "entry_bar_date": None,
                "entry_price": None,
                "exit_signal_id": None,
                "details": None,
            }
        return {
            "ticker": row.ticker,
            "strategy_id": row.strategy_id,
            "strategy_version": row.strategy_version,
            "parameter_set_id": row.parameter_set_id,
            "state": row.state,
            "entry_signal_id": row.entry_signal_id,
            "entry_bar_date": row.entry_bar_date,
            "entry_price": row.entry_price,
            "exit_signal_id": row.exit_signal_id,
            "details": row.details,
        }


def _norm(ticker: Any) -> str:
    return str(ticker or "").strip().upper()


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)
