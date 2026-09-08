# -*- coding: utf-8 -*-
"""Phase 4 tests: SignalEvent persistence + duplicate protection.

A minimal signal job wires the real quality gate (Phase 3) and the shared
strategy engine (Phase 2) into ``SignalEventService``:

    bars -> check_bars_for_signals -> strategy_engine.evaluate
         -> record_and_notify (CONFIRMED notifies once; repeats never resend)
"""

import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.services.market_data_quality import check_bars_for_signals
from src.services.signal_event_service import (
    SignalEventService,
    build_signal_id,
)
from src.services.strategy_engine import evaluate
from src.storage import Base

EASTERN = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 4, 20, 0, tzinfo=EASTERN)  # Fri after close -> session 09-04
STRATEGY_ID = "composite"
STRATEGY_VERSION = "F@v2"
PARAM_SET = "default"


def _bars_ending(target, count):
    closes = [
        round(100.0 + 0.02 * i + 6.0 * math.sin(i / 18.0) + 2.0 * math.sin(i / 7.0), 4)
        for i in range(count)
    ]
    bars = []
    day = target - timedelta(days=count - 1)
    for close in closes:
        bars.append(
            {
                "date": day.isoformat(),
                "open": float(close),
                "high": float(close) + 0.06,
                "low": float(close) - 0.06,
                "close": float(close),
                "volume": 1_000_000.0,
            }
        )
        day += timedelta(days=1)
    return bars


def _service(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/signals.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return SignalEventService(session_factory=factory)


def _run_signal_job(bars, service, notifications, now=NOW):
    """One scheduler tick: gate -> evaluate -> record (+notify once)."""
    quality = check_bars_for_signals(
        bars, market="us", provider="tencent",
        adjustment_mode="none", current_time=now,
    )
    if not quality.actionable:
        evaluation = evaluate(bars, strategy="A")
        for decision in evaluation["decisions"]:
            if decision.action == "HOLD":
                continue
            service.record_blocked(
                ticker="AAPL", strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION, parameter_set_id=PARAM_SET,
                bar_date=decision.date, action=decision.action,
                reason=quality.reason or "BLOCKED",
                status="BLOCKED" if quality.status == "BLOCKED" else "PREVIEW",
                provider="tencent", adjustment_mode="none",
                data_timestamp=quality.latest_bar_date.isoformat(),
            )
        return {"actionable": False, "notified": 0}
    evaluation = evaluate(bars, strategy="A")
    notified = 0
    for decision in evaluation["decisions"]:
        if decision.action == "HOLD":
            continue
        bar = next(b for b in bars if b["date"] == decision.date)
        _, _, sent = service.record_and_notify(
            notifications.append,
            ticker="AAPL", strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION, parameter_set_id=PARAM_SET,
            bar_date=decision.date, action=decision.action,
            score=decision.buy_score if decision.action == "BUY" else decision.sell_score,
            threshold=decision.buy_threshold,
            factors=decision.factors, signal_bar_ohlcv=bar,
            provider="tencent", adjustment_mode="none",
            data_timestamp=decision.date, status="CONFIRMED",
        )
        notified += sent
    return {"actionable": True, "notified": notified}


def test_repeated_runs_produce_one_signal_and_one_notification(tmp_path):
    service = _service(tmp_path)
    bars = _bars_ending(date(2026, 9, 4), 300)
    notifications = []

    first = _run_signal_job(bars, service, notifications)
    assert first["actionable"] is True
    assert first["notified"] > 0
    confirmed = service.count(ticker="AAPL", status="CONFIRMED")
    assert confirmed == first["notified"] == len(notifications)

    # 19 more identical ticks: no new rows, no new notifications.
    for _ in range(19):
        tick = _run_signal_job(bars, service, notifications)
        assert tick["notified"] == 0
    assert service.count(ticker="AAPL", status="CONFIRMED") == confirmed
    assert len(notifications) == confirmed


def test_restart_produces_no_duplicates(tmp_path):
    bars = _bars_ending(date(2026, 9, 4), 300)
    notifications = []
    _run_signal_job(bars, _service(tmp_path), notifications)
    before = len(notifications)
    assert before > 0

    # Simulate an app restart: a fresh service on the same database file.
    restarted = _service(tmp_path)
    tick = _run_signal_job(bars, restarted, notifications)
    assert tick["notified"] == 0
    assert len(notifications) == before


def test_signal_id_is_deterministic_and_lookup_works(tmp_path):
    service = _service(tmp_path)
    first = build_signal_id("aapl", "F@v2", "default", "2026-09-04", "buy")
    second = build_signal_id("AAPL", "F@v2", "default", "2026-09-04", "BUY")
    assert first == second

    result = service.record_decision(
        ticker="AAPL", strategy_id=STRATEGY_ID, strategy_version=STRATEGY_VERSION,
        parameter_set_id=PARAM_SET, bar_date="2026-09-04", action="BUY",
        score=7, threshold=6, status="CONFIRMED",
    )
    assert result.created is True
    assert result.record["signal_id"] == first
    assert service.get(first)["bar_timestamp"] == "2026-09-04"

    again = service.record_decision(
        ticker="AAPL", strategy_id=STRATEGY_ID, strategy_version=STRATEGY_VERSION,
        parameter_set_id=PARAM_SET, bar_date="2026-09-04", action="BUY",
        score=7, threshold=6, status="CONFIRMED",
    )
    assert again.created is False
    assert service.count() == 1


def test_blocked_signals_never_notify_and_stay_singular(tmp_path):
    service = _service(tmp_path)
    stale_bars = _bars_ending(date(2026, 9, 3), 300)  # missing the 09-04 session
    notifications = []
    for _ in range(3):
        tick = _run_signal_job(stale_bars, service, notifications)
        assert tick["actionable"] is False
        assert tick["notified"] == 0
    assert notifications == []
    # Repeats collapse onto the same BLOCKED rows.
    total = service.count(ticker="AAPL")
    assert total == service.count(ticker="AAPL", status="BLOCKED")
    assert total > 0


def test_lifecycle_transitions_and_validation(tmp_path):
    service = _service(tmp_path)
    result = service.record_decision(
        ticker="TSLA", strategy_id=STRATEGY_ID, strategy_version=STRATEGY_VERSION,
        parameter_set_id=PARAM_SET, bar_date="2026-09-04", action="SELL",
        score=6, threshold=6, status="CONFIRMED",
    )
    assert result.created is True
    assert service.mark_status(result.record["signal_id"], "EXECUTED") is True
    assert service.get(result.record["signal_id"])["status"] == "EXECUTED"
    assert service.mark_status("0" * 64, "CANCELLED") is False
    try:
        service.record_decision(
            ticker="TSLA", strategy_id=STRATEGY_ID, strategy_version=STRATEGY_VERSION,
            parameter_set_id=PARAM_SET, bar_date="2026-09-04", action="SELL",
            status="NOPE",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("invalid status must raise")
