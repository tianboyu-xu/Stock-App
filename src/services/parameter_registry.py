# -*- coding: utf-8 -*-
"""
参数注册表（Parameter Registry）：候选 -> 晋升 -> 回滚
====================================================

规则（Rule 6）：

- ``run_auto_tune()`` 只允许创建 ``CANDIDATE``（接线见后续任务；
  本模块提供 ``create_candidate`` 作为唯一写入入口）。
- 生产参数只能通过显式晋升变更（``promote_to_production``，
  对应 UI 上的“晋升”按钮）。
- 晋升时旧 PRODUCTION 转为 RETIRED 并保留 ``parent_id`` 链，
  ``rollback`` 可恢复上一版生产参数。
- 信号落库时记录的 ``parameter_set_id`` 取 ``ps-<row_id>``，
  保证每笔信号可精确回溯到参数版本（Rule 8）。
"""

from __future__ import annotations

import json
from contextlib import closing

from src.repositories.strategy_transactions import begin_strategy_write
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional

STATUS_CANDIDATE = "CANDIDATE"
STATUS_SHADOW = "SHADOW"
STATUS_APPROVED = "APPROVED"
STATUS_PRODUCTION = "PRODUCTION"
STATUS_RETIRED = "RETIRED"

STATUSES = (
    STATUS_CANDIDATE,
    STATUS_SHADOW,
    STATUS_APPROVED,
    STATUS_PRODUCTION,
    STATUS_RETIRED,
)

_PROMOTABLE = (STATUS_CANDIDATE, STATUS_SHADOW, STATUS_APPROVED)


def _default_session_factory():
    from src.storage import DatabaseManager

    return DatabaseManager.get_instance().get_session()


def parameter_set_id_for(row_id: int) -> str:
    """信号记录用的稳定参数集 ID。"""
    return f"ps-{int(row_id)}"


class ParameterRegistry:
    """参数版本注册表（session 由调用方注入，便于测试隔离）。"""

    def __init__(self, session_factory: Optional[Callable[[], Any]] = None) -> None:
        self._session_factory = session_factory or _default_session_factory

    def create_candidate(
        self,
        *,
        scope_key: str,
        strategy_generation: str,
        parameters: Mapping[str, Any],
        training_window: Optional[tuple] = None,
        validation_window: Optional[tuple] = None,
        test_window: Optional[tuple] = None,
        train_metrics: Optional[Mapping[str, Any]] = None,
        validation_metrics: Optional[Mapping[str, Any]] = None,
        test_metrics: Optional[Mapping[str, Any]] = None,
        robustness_score: Optional[float] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建 CANDIDATE（绝不触碰当前 PRODUCTION）。"""
        from src.storage import StrategyParameterSetRecord

        with closing(self._session_factory()) as session:
            row = StrategyParameterSetRecord(
                scope_key=str(scope_key),
                strategy_generation=str(strategy_generation),
                parameters_json=json.dumps(dict(parameters), sort_keys=True, default=str),
                training_start=training_window[0] if training_window else None,
                training_end=training_window[1] if training_window else None,
                validation_start=validation_window[0] if validation_window else None,
                validation_end=validation_window[1] if validation_window else None,
                test_start=test_window[0] if test_window else None,
                test_end=test_window[1] if test_window else None,
                train_metrics_json=_dump(train_metrics),
                validation_metrics_json=_dump(validation_metrics),
                test_metrics_json=_dump(test_metrics),
                robustness_score=robustness_score,
                status=STATUS_CANDIDATE,
            )
            if note is not None:
                row.note = note
            session.add(row)
            session.commit()
            session.refresh(row)
            return _to_dict(row)

    def get_production(self, scope_key: str, strategy_generation: str) -> Optional[Dict[str, Any]]:
        """查询当前生产参数（无则返回 None）。"""
        from src.storage import StrategyParameterSetRecord

        with closing(self._session_factory()) as session:
            row = (
                session.query(StrategyParameterSetRecord)
                .filter_by(
                    scope_key=str(scope_key),
                    strategy_generation=str(strategy_generation),
                    status=STATUS_PRODUCTION,
                )
                .order_by(StrategyParameterSetRecord.id.desc())
                .first()
            )
            return _to_dict(row) if row is not None else None

    def promote_to_production(self, record_id: int) -> Dict[str, Any]:
        """显式晋升：CANDIDATE/SHADOW/APPROVED -> PRODUCTION。

        同一 (scope, generation) 的旧 PRODUCTION 转为 RETIRED 并成为
        新版本的 parent，保证可回滚。
        """
        from src.storage import StrategyParameterSetRecord

        with closing(self._session_factory()) as session:
            begin_strategy_write(session)
            row = session.query(StrategyParameterSetRecord).filter_by(id=int(record_id)).one_or_none()
            if row is None:
                raise ValueError(f"参数版本不存在: {record_id}")
            if row.status == STATUS_PRODUCTION:
                return _to_dict(row)
            if row.status not in _PROMOTABLE:
                raise ValueError(f"只有 {_PROMOTABLE} 可晋升，当前为 {row.status}")
            previous = (
                session.query(StrategyParameterSetRecord)
                .filter_by(
                    scope_key=row.scope_key,
                    strategy_generation=row.strategy_generation,
                    status=STATUS_PRODUCTION,
                )
                .order_by(StrategyParameterSetRecord.id.desc())
                .first()
            )
            if previous is not None:
                previous.status = STATUS_RETIRED
                previous.updated_at = _utcnow()
                row.parent_id = previous.id
            row.status = STATUS_PRODUCTION
            row.updated_at = _utcnow()
            session.commit()
            session.refresh(row)
            return _to_dict(row)

    def rollback(self, record_id: int) -> Dict[str, Any]:
        """回滚到指定的 RETIRED 版本（须同 scope+generation）。"""
        from src.storage import StrategyParameterSetRecord

        with closing(self._session_factory()) as session:
            begin_strategy_write(session)
            target = session.query(StrategyParameterSetRecord).filter_by(id=int(record_id)).one_or_none()
            if target is None:
                raise ValueError(f"参数版本不存在: {record_id}")
            if target.status != STATUS_RETIRED:
                raise ValueError(f"只有 RETIRED 版本可回滚，当前为 {target.status}")
            current = (
                session.query(StrategyParameterSetRecord)
                .filter_by(
                    scope_key=target.scope_key,
                    strategy_generation=target.strategy_generation,
                    status=STATUS_PRODUCTION,
                )
                .order_by(StrategyParameterSetRecord.id.desc())
                .first()
            )
            if current is not None:
                current.status = STATUS_RETIRED
                current.updated_at = _utcnow()
            target.status = STATUS_PRODUCTION
            target.updated_at = _utcnow()
            session.commit()
            session.refresh(target)
            return _to_dict(target)

    def list_versions(self, scope_key: str, strategy_generation: str) -> List[Dict[str, Any]]:
        """版本历史（id 升序，即创建时间序）。"""
        from src.storage import StrategyParameterSetRecord

        with closing(self._session_factory()) as session:
            rows = (
                session.query(StrategyParameterSetRecord)
                .filter_by(scope_key=str(scope_key), strategy_generation=str(strategy_generation))
                .order_by(StrategyParameterSetRecord.id.asc())
                .all()
            )
            return [_to_dict(row) for row in rows]


def _dump(value: Optional[Mapping[str, Any]]) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(dict(value), sort_keys=True, default=str)


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": row.id,
        "parameter_set_id": parameter_set_id_for(row.id),
        "scope_key": row.scope_key,
        "strategy_generation": row.strategy_generation,
        "parameters": json.loads(row.parameters_json or "{}"),
        "training_window": [row.training_start, row.training_end],
        "validation_window": [row.validation_start, row.validation_end],
        "test_window": [row.test_start, row.test_end],
        "train_metrics": json.loads(row.train_metrics_json) if row.train_metrics_json else None,
        "validation_metrics": json.loads(row.validation_metrics_json) if row.validation_metrics_json else None,
        "test_metrics": json.loads(row.test_metrics_json) if row.test_metrics_json else None,
        "robustness_score": row.robustness_score,
        "status": row.status,
        "parent_id": row.parent_id,
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
