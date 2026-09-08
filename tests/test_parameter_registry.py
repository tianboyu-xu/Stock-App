# -*- coding: utf-8 -*-
"""Phase 8 tests: parameter registry (candidate/promote/rollback)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.services.parameter_registry import ParameterRegistry, parameter_set_id_for
from src.storage import Base


def _registry(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/registry.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return ParameterRegistry(session_factory=factory)


def _candidate(registry, params=None):
    return registry.create_candidate(
        scope_key="AAPL",
        strategy_generation="F",
        parameters=params or {"composite_buy_threshold": 6},
        training_window=("2020-01-01", "2022-01-01"),
        validation_window=("2022-01-01", "2023-01-01"),
        test_window=("2023-01-01", "2024-01-01"),
        robustness_score=0.8,
    )


def test_auto_tune_style_candidate_leaves_production_unchanged(tmp_path):
    registry = _registry(tmp_path)
    assert registry.get_production("AAPL", "F") is None
    first = _candidate(registry)
    assert first["status"] == "CANDIDATE"
    assert first["parameter_set_id"] == parameter_set_id_for(first["id"])
    # 新候选不得影响生产版本（此时仍为空）。
    assert registry.get_production("AAPL", "F") is None
    second = _candidate(registry, {"composite_buy_threshold": 5})
    assert registry.get_production("AAPL", "F") is None
    assert second["id"] != first["id"]


def test_promote_candidate_and_retire_previous(tmp_path):
    registry = _registry(tmp_path)
    first = _candidate(registry, {"composite_buy_threshold": 6})
    prod = registry.promote_to_production(first["id"])
    assert prod["status"] == "PRODUCTION"
    assert registry.get_production("AAPL", "F")["id"] == first["id"]

    second = _candidate(registry, {"composite_buy_threshold": 5})
    prod2 = registry.promote_to_production(second["id"])
    assert prod2["status"] == "PRODUCTION"
    assert prod2["parent_id"] == first["id"]
    assert registry.get_production("AAPL", "F")["id"] == second["id"]
    history = {v["id"]: v["status"] for v in registry.list_versions("AAPL", "F")}
    assert history[first["id"]] == "RETIRED"
    assert history[second["id"]] == "PRODUCTION"


def test_rollback_restores_previous_version(tmp_path):
    registry = _registry(tmp_path)
    first = _candidate(registry, {"composite_buy_threshold": 6})
    second = _candidate(registry, {"composite_buy_threshold": 5})
    registry.promote_to_production(first["id"])
    registry.promote_to_production(second["id"])
    restored = registry.rollback(first["id"])
    assert restored["status"] == "PRODUCTION"
    assert registry.get_production("AAPL", "F")["id"] == first["id"]
    history = {v["id"]: v["status"] for v in registry.list_versions("AAPL", "F")}
    assert history[second["id"]] == "RETIRED"


def test_promote_rejects_retired_and_missing(tmp_path):
    registry = _registry(tmp_path)
    first = _candidate(registry)
    second = _candidate(registry)
    registry.promote_to_production(first["id"])
    registry.promote_to_production(second["id"])  # first -> RETIRED
    with pytest.raises(ValueError):
        registry.rollback(second["id"])  # PRODUCTION 不可作为回滚目标
    with pytest.raises(ValueError):
        registry.promote_to_production(999999)


def test_signals_record_exact_parameter_set_id(tmp_path):
    from src.services.signal_event_service import SignalEventService

    registry = _registry(tmp_path)
    candidate = _candidate(registry)
    prod = registry.promote_to_production(candidate["id"])
    # 信号行写入晋升后的精确参数集 ID。
    assert prod["parameter_set_id"].startswith("ps-")
    events = SignalEventService(session_factory=registry._session_factory)
    result = events.record_decision(
        ticker="AAPL", strategy_id="composite", strategy_version="F@v2",
        parameter_set_id=prod["parameter_set_id"],
        bar_date="2026-09-04", action="BUY", status="CONFIRMED",
    )
    assert result.created is True
    assert result.record["parameter_set_id"] == prod["parameter_set_id"]
