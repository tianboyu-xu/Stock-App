# -*- coding: utf-8 -*-
"""
信号事件服务（SignalEvent）：持久化 + 去重 + 生命周期
====================================================

职责：

1. 把 ``strategy_engine`` 的逐 bar 决策落库为 ``SignalEventRecord``，
   附带策略版本、参数版本与数据复现元数据（Rule 8）。
2. 幂等：``signal_id`` 是 (ticker, strategy_version, parameter_set_id,
   signal bar, action) 的确定性 SHA256；同一输入重复执行只返回已存在的
   行，不产生重复通知（Rule 9）。
3. 生命周期：PREVIEW / CONFIRMED / BLOCKED / CANCELLED / EXECUTED /
   EXPIRED。首次确认（含预览转确认）只尝试通知一次，不保证外部渠道恰好送达一次。
"""

from __future__ import annotations

import hashlib
import json
from contextlib import closing

from src.repositories.strategy_transactions import begin_strategy_write
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

STATUSES = ("PREVIEW", "CONFIRMED", "BLOCKED", "CANCELLED", "EXECUTED", "EXPIRED")

_ACTIONABLE_STATUSES = ("CONFIRMED",)


def _normalize_part(value: Any) -> str:
    return str(value if value is not None else "").strip().upper()


def build_signal_id(
    ticker: Any,
    strategy_version: Any,
    parameter_set_id: Any,
    signal_bar: Any,
    action: Any,
) -> str:
    """确定性幂等键：SHA256(ticker|版本|参数集|信号 bar|动作)。"""
    parts = (
        _normalize_part(ticker),
        _normalize_part(strategy_version),
        _normalize_part(parameter_set_id),
        _normalize_part(signal_bar),
        _normalize_part(action),
    )
    if any(not part or "|" in part for part in parts):
        raise ValueError("Signal identity parts must be nonempty and cannot contain '|'")
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_data_hash(
    signal_bar_ohlcv: Mapping[str, Any],
    provider: Any,
    adjustment_mode: Any,
) -> str:
    """信号 bar OHLCV + 数据源声明的规范哈希（复现用）。"""
    payload = {
        "open": signal_bar_ohlcv.get("open"),
        "high": signal_bar_ohlcv.get("high"),
        "low": signal_bar_ohlcv.get("low"),
        "close": signal_bar_ohlcv.get("close"),
        "volume": signal_bar_ohlcv.get("volume"),
        "date": signal_bar_ohlcv.get("date"),
        "provider": provider,
        "adjustment_mode": adjustment_mode,
    }
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RecordResult:
    """落库结果：record 为行字典，created 标识是否为本次新建。"""

    record: Dict[str, Any]
    created: bool
    became_confirmed: bool = False


def _default_session_factory():
    from src.storage import DatabaseManager

    return DatabaseManager.get_instance().get_session()


class SignalEventService:
    """信号事件持久化服务（session 由调用方注入，便于测试隔离）。"""

    def __init__(self, session_factory: Optional[Callable[[], Any]] = None) -> None:
        self._session_factory = session_factory or _default_session_factory

    def record_decision(
        self,
        *,
        ticker: str,
        strategy_id: str,
        strategy_version: str,
        parameter_set_id: str,
        bar_date: str,
        action: str,
        score: Optional[int] = None,
        threshold: Optional[int] = None,
        signal_strength: Optional[float] = None,
        factors: Optional[Mapping[str, Any]] = None,
        signal_bar_ohlcv: Optional[Mapping[str, Any]] = None,
        provider: Optional[str] = None,
        adjustment_mode: Optional[str] = None,
        data_timestamp: Optional[str] = None,
        status: str = "CONFIRMED",
        details: Optional[str] = None,
    ) -> RecordResult:
        """记录一次策略决策；重复输入返回已存在行（created=False）。"""
        from src.storage import SignalEventRecord

        if status not in STATUSES:
            raise ValueError(f"未知的信号状态: {status!r}")
        if str(action).strip().upper() not in ("BUY", "SELL", "HOLD"):
            raise ValueError(f"Unknown signal action: {action!r}")
        signal_id = build_signal_id(
            ticker, strategy_version, parameter_set_id, bar_date, action,
        )
        data_hash: Optional[str] = None
        if signal_bar_ohlcv is not None:
            data_hash = compute_data_hash(signal_bar_ohlcv, provider, adjustment_mode)
        with closing(self._session_factory()) as session:
            begin_strategy_write(session)
            existing = session.query(SignalEventRecord).filter_by(signal_id=signal_id).one_or_none()
            if existing is not None:
                if existing.strategy_id != str(strategy_id):
                    raise ValueError("Signal identity conflicts with another strategy; use a unique strategy version")
                if existing.status not in ("PREVIEW", "BLOCKED") or status not in ("PREVIEW", "BLOCKED", "CONFIRMED"):
                    return RecordResult(record=_to_dict(existing), created=False)
            row = existing or SignalEventRecord(signal_id=signal_id)
            values = dict(
                signal_id=signal_id,
                ticker=str(ticker).strip().upper(),
                strategy_id=str(strategy_id),
                strategy_version=str(strategy_version),
                parameter_set_id=str(parameter_set_id),
                bar_timestamp=str(bar_date),
                action=str(action).strip().upper(),
                score=score,
                threshold=threshold,
                signal_strength=signal_strength,
                provider=provider,
                adjustment_mode=adjustment_mode or "unknown",
                data_timestamp=data_timestamp,
                data_hash=data_hash,
                factors_json=json.dumps(dict(factors or {}), sort_keys=True, default=str),
                status=status,
                details=details,
            )
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.add(row)
            session.commit()
            session.refresh(row)
            return RecordResult(record=_to_dict(row), created=existing is None,
                                became_confirmed=status == "CONFIRMED")

    def record_blocked(
        self,
        *,
        ticker: str,
        strategy_id: str,
        strategy_version: str,
        parameter_set_id: str,
        bar_date: str,
        action: str,
        reason: str,
        status: str = "BLOCKED",
        provider: Optional[str] = None,
        adjustment_mode: Optional[str] = None,
        data_timestamp: Optional[str] = None,
        details: Optional[str] = None,
    ) -> RecordResult:
        """记录被阻止/预览的信号观察（同样幂等，不触发通知）。"""
        if status not in ("BLOCKED", "PREVIEW"):
            raise ValueError(f"record_blocked 仅支持 BLOCKED/PREVIEW: {status!r}")
        return self.record_decision(
            ticker=ticker,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            parameter_set_id=parameter_set_id,
            bar_date=bar_date,
            action=action,
            provider=provider,
            adjustment_mode=adjustment_mode,
            data_timestamp=data_timestamp,
            status=status,
            details=details or reason,
        )

    def mark_status(self, signal_id: str, status: str, details: Optional[str] = None) -> bool:
        """推进生命周期状态；返回行是否存在。"""
        from src.storage import SignalEventRecord

        if status not in STATUSES:
            raise ValueError(f"未知的信号状态: {status!r}")
        with closing(self._session_factory()) as session:
            begin_strategy_write(session)
            row = session.query(SignalEventRecord).filter_by(signal_id=signal_id).one_or_none()
            if row is None:
                return False
            transitions = {
                "PREVIEW": {"BLOCKED", "CANCELLED", "EXPIRED"},
                "BLOCKED": {"PREVIEW", "CANCELLED", "EXPIRED"},
                "CONFIRMED": {"CANCELLED", "EXECUTED", "EXPIRED"},
            }
            if status != row.status and status not in transitions.get(row.status, set()):
                raise ValueError(f"Invalid signal transition: {row.status} -> {status}")
            row.status = status
            if details is not None:
                row.details = details
            row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.commit()
            return True

    def get(self, signal_id: str) -> Optional[Dict[str, Any]]:
        """按幂等键查询（重启后去重用）。"""
        from src.storage import SignalEventRecord

        with closing(self._session_factory()) as session:
            row = session.query(SignalEventRecord).filter_by(signal_id=signal_id).one_or_none()
            return _to_dict(row) if row is not None else None

    def count(self, ticker: Optional[str] = None, status: Optional[str] = None) -> int:
        """计数（监控/测试用）。"""
        from src.storage import SignalEventRecord

        with closing(self._session_factory()) as session:
            query = session.query(SignalEventRecord)
            if ticker is not None:
                query = query.filter_by(ticker=str(ticker).strip().upper())
            if status is not None:
                query = query.filter_by(status=status)
            return query.count()

    def list_recent(
        self,
        ticker: Optional[str] = None,
        statuses: Optional[Sequence[str]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """最近信号（信号监控页/API 复用）。"""
        from src.storage import SignalEventRecord

        with closing(self._session_factory()) as session:
            query = session.query(SignalEventRecord).order_by(SignalEventRecord.id.desc())
            if ticker is not None:
                query = query.filter_by(ticker=str(ticker).strip().upper())
            if statuses:
                query = query.filter(SignalEventRecord.status.in_(list(statuses)))
            return [_to_dict(row) for row in query.limit(max(1, limit)).all()]

    def record_and_notify(
        self,
        notify: Callable[[Dict[str, Any]], Any],
        **kwargs: Any,
    ) -> Tuple[Dict[str, Any], bool, bool]:
        """落库并在满足条件时触发一次通知。

        返回 (record, created, notified)。首次确认的 BUY/SELL 才尝试通知；
        callback 返回 False 表示失败，异常继续向上传播，失败类型写入 details。
        重复运行不自动重发。进程在提交后崩溃仍可能丢通知；可靠重试需要
        outbox 和接收方幂等支持，不能把此接口视为 exactly-once delivery。
        """
        result = self.record_decision(**kwargs)
        notified = False
        if (result.became_confirmed and result.record["status"] in _ACTIONABLE_STATUSES
                and result.record["action"] in ("BUY", "SELL")):
            def record_failure(error_type):
                from src.storage import SignalEventRecord

                with closing(self._session_factory()) as session:
                    begin_strategy_write(session)
                    row = session.query(SignalEventRecord).filter_by(
                        signal_id=result.record["signal_id"],
                    ).one()
                    row.details = json.dumps({
                        "decision_details": row.details,
                        "notification": {"status": "FAILED", "error_type": error_type},
                    })
                    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    session.commit()

            try:
                notified = notify(result.record) is not False
            except Exception as error:
                record_failure(type(error).__name__)
                raise
            if not notified:
                record_failure("CallbackReturnedFalse")
        return result.record, result.created, notified



def _to_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": row.id,
        "signal_id": row.signal_id,
        "ticker": row.ticker,
        "strategy_id": row.strategy_id,
        "strategy_version": row.strategy_version,
        "parameter_set_id": row.parameter_set_id,
        "bar_timestamp": row.bar_timestamp,
        "action": row.action,
        "score": row.score,
        "threshold": row.threshold,
        "signal_strength": row.signal_strength,
        "provider": row.provider,
        "adjustment_mode": row.adjustment_mode,
        "data_timestamp": row.data_timestamp,
        "data_hash": row.data_hash,
        "factors": json.loads(row.factors_json or "{}"),
        "status": row.status,
        "details": row.details,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
