# -*- coding: utf-8 -*-
"""Phase 5 tests: trading-position state machine + restart persistence."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.services.trading_state_service import TradingStateService
from src.storage import Base

SCOPE = ("AAPL", "composite", "F@v2", "default")


def _service(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/state.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return TradingStateService(session_factory=factory)


def test_buy_from_flat_creates_one_entry(tmp_path):
    service = _service(tmp_path)
    assert service.get_state(*SCOPE)["state"] == "FLAT"
    state, accepted = service.on_signal(*SCOPE, action="BUY", signal_id="sig-1")
    assert accepted is True
    assert state["state"] == "ENTRY_SIGNALLED"
    state = service.confirm_execution(*SCOPE)
    assert state["state"] == "ENTRY_PENDING"
    state = service.confirm_fill(*SCOPE, fill_price=100.5)
    assert state["state"] == "LONG"
    assert state["entry_price"] == 100.5


def test_second_buy_while_long_does_not_create_another_entry(tmp_path):
    service = _service(tmp_path)
    service.on_signal(*SCOPE, action="BUY", signal_id="sig-1")
    service.confirm_execution(*SCOPE)
    service.confirm_fill(*SCOPE, fill_price=100.0)
    state, accepted = service.on_signal(*SCOPE, action="BUY", signal_id="sig-2")
    assert accepted is False
    assert state["state"] == "LONG"
    assert state["entry_signal_id"] == "sig-1"


def test_sell_from_long_creates_one_exit(tmp_path):
    service = _service(tmp_path)
    service.on_signal(*SCOPE, action="BUY", signal_id="sig-1")
    service.confirm_execution(*SCOPE)
    service.confirm_fill(*SCOPE, fill_price=100.0)
    state, accepted = service.on_signal(*SCOPE, action="SELL", signal_id="sig-9")
    assert accepted is True
    assert state["state"] == "EXIT_SIGNALLED"
    assert service.confirm_execution(*SCOPE)["state"] == "EXIT_PENDING"
    final = service.confirm_fill(*SCOPE)
    assert final["state"] == "FLAT"
    assert final["entry_price"] is None


def test_sell_from_flat_is_ignored(tmp_path):
    service = _service(tmp_path)
    state, accepted = service.on_signal(*SCOPE, action="SELL", signal_id="sig-x")
    assert accepted is False
    assert state["state"] == "FLAT"


def test_restart_preserves_position_state(tmp_path):
    service = _service(tmp_path)
    service.on_signal(*SCOPE, action="BUY", signal_id="sig-1")
    service.confirm_execution(*SCOPE)
    service.confirm_fill(*SCOPE, fill_price=100.0)

    restarted = _service(tmp_path)
    assert restarted.get_state(*SCOPE)["state"] == "LONG"
    # 重启后重复的 BUY 仍被拒绝，不会叠加建仓。
    state, accepted = restarted.on_signal(*SCOPE, action="BUY", signal_id="sig-2")
    assert accepted is False
    assert state["state"] == "LONG"


def test_reset_returns_to_flat(tmp_path):
    service = _service(tmp_path)
    service.on_signal(*SCOPE, action="BUY", signal_id="sig-1")
    final = service.reset(*SCOPE, details="manual reconcile")
    assert final["state"] == "FLAT"
    assert final["details"] == "manual reconcile"
