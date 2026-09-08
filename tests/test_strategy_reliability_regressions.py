"""Regression coverage for the reliability components; not live deployment evidence."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core import trading_calendar
from src.services.execution_policy import evaluate_entry
from src.services.indicator_service import compute_indicators
from src.services.market_data_quality import check_bars_for_signals
from src.services.parameter_registry import ParameterRegistry
from src.services.risk_engine import build_execution_plan
from src.services.signal_event_service import SignalEventService
from src.services.strategy_engine import evaluate, evaluate_signals, prepare_base_series
from src.services.trading_state_service import TradingStateService
from src.storage import Base
from tests.test_strategy_engine import FIXTURE_BARS

NOW = datetime(2026, 9, 4, 20, tzinfo=ZoneInfo("America/New_York"))
SCOPE = ("AAPL", "composite", "A@v2", "ps-1")
EVENT = dict(ticker=SCOPE[0], strategy_id=SCOPE[1], strategy_version=SCOPE[2],
             parameter_set_id=SCOPE[3], bar_date="2026-09-04", action="BUY")


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/reliability.db")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


@pytest.mark.parametrize("parameters", [
    {"rsi_period": 7}, {"macd_fast": 5, "macd_slow": 18},
    {"kdj_period": 5}, {"rsi_smooth_fast": 3},
    {"rsi_period": 7, "macd_fast": 5, "kdj_period": 5},
])
def test_custom_periods_match_chart_and_cached_backtest(parameters):
    chart = compute_indicators(FIXTURE_BARS, parameters)["composite"]
    cached = evaluate_signals(prepare_base_series(FIXTURE_BARS), parameters)
    decisions = evaluate(FIXTURE_BARS, parameters=parameters)["decisions"]
    for key in cached:
        assert cached[key] == chart[key]
    assert [(d.buy_score, d.sell_score) for d in decisions] == list(zip(chart["buy_score"], chart["sell_score"]))
    assert [d.action for d in decisions] == [
        "BUY" if buy is not None else "SELL" if sell is not None else "HOLD"
        for buy, sell in zip(chart["buy_signal"], chart["sell_signal"])
    ]


def quality(bars=None, **kwargs):
    if bars is None:
        bars = [dict(date="2026-09-04", open=100, high=102, low=98, close=101, volume=1000)]
    return check_bars_for_signals(bars, market=kwargs.pop("market", "us"), current_time=NOW, **kwargs)


@pytest.mark.parametrize("field,value", [("high", float("inf")), ("open", True),
    ("close", 103), ("low", 101), ("volume", -1), ("volume", float("inf")),
    ("date", "2026-09-04junk")])
def test_invalid_bars_cannot_be_confirmed(field, value):
    bar = dict(date="2026-09-04", open=100, high=102, low=98, close=101, volume=1000)
    bar[field] = value
    assert quality([bar]).status == "BLOCKED"


def test_calendar_failure_blocks_instead_of_confirming_today(monkeypatch):
    monkeypatch.setattr(trading_calendar, "_XCALS_AVAILABLE", False)
    assert quality().reason == "CALENDAR_UNAVAILABLE"
    assert trading_calendar.get_effective_trading_date("us", NOW) == NOW.date()


def test_unknown_market_and_unsorted_dates_block():
    assert quality(market="bogus").reason == "UNKNOWN_MARKET"
    bars = [dict(date=day, open=100, high=102, low=98, close=101, volume=1000)
            for day in ("2026-09-05", "2026-09-04")]
    assert quality(bars).status == "BLOCKED"


@pytest.mark.parametrize("changes,reason", [
    ({"next_open": 0}, "INVALID_PRICE"), ({"signal_close": float("nan")}, "INVALID_PRICE"),
    ({"next_open": float("inf")}, "INVALID_PRICE"),
    ({"max_entry_gap_atr": -1}, "INVALID_GAP_LIMIT"),
    ({"max_entry_gap_atr": float("nan")}, "INVALID_GAP_LIMIT"),
    ({"max_entry_gap_atr": 1, "atr": float("inf")}, "NO_ATR_DATA"),
])
def test_execution_rejects_invalid_prices_and_limits(changes, reason):
    args = dict(signal_close=100, next_open=101)
    args.update(changes)
    assert evaluate_entry(**args)["reason"] == reason


@pytest.mark.parametrize("changes", [
    {"stop_price": 105}, {"stop_price": float("inf")}, {"portfolio_value": float("inf")},
    {"risk_per_trade": float("inf")}, {"max_single_stock_pct": float("nan")},
    {"current_positions_value": -100}, {"maximum_entry": 99}, {"action": "SELL"},
])
def test_risk_rejects_invalid_long_plan(changes):
    args = dict(ticker="AAPL", portfolio_value=100000, entry_reference=100, stop_price=95)
    args.update(changes)
    assert not build_execution_plan(**args).approved


def test_sizing_uses_maximum_fill_price_for_risk_and_caps():
    plan = build_execution_plan(ticker="AAPL", portfolio_value=100000,
                                entry_reference=100, maximum_entry=110, stop_price=95)
    assert plan.approved
    assert plan.suggested_shares == 66
    assert plan.suggested_position_value == 7260
    assert plan.portfolio_risk_pct <= 1


def test_parallel_signal_creation_notifies_once_and_survives_restart(factory):
    notified = []
    def run(_):
        return SignalEventService(factory).record_and_notify(notified.append, **EVENT)
    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(run, range(20)))
    assert sum(created for _, created, _ in results) == 1
    assert len(notified) == 1
    assert SignalEventService(factory).count() == 1
    assert not run(21)[2]


def test_preview_can_confirm_once_with_final_metadata(factory):
    service = SignalEventService(factory)
    preview = service.record_decision(**EVENT, status="PREVIEW", score=2)
    notified = []
    record, created, sent = service.record_and_notify(notified.append, **EVENT, score=6)
    assert not created and sent
    assert record["id"] == preview.record["id"] and record["score"] == 6
    assert not service.record_and_notify(notified.append, **EVENT)[2]
    assert len(notified) == 1
    service.mark_status(record["signal_id"], "EXECUTED")
    with pytest.raises(ValueError, match="Invalid signal transition"):
        service.mark_status(record["signal_id"], "CONFIRMED")


def test_false_notification_result_is_not_reported_successful(factory):
    assert not SignalEventService(factory).record_and_notify(lambda _: False, **EVENT)[2]


def test_parallel_position_entry_is_accepted_once(factory):
    def run(_):
        return TradingStateService(factory).on_signal(*SCOPE, "BUY")
    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(run, range(20)))
    assert sum(accepted for _, accepted in results) == 1


@pytest.mark.parametrize("price", [None, 0, -1, float("inf"), float("nan"), True])
def test_invalid_fill_does_not_advance_pending_position(factory, price):
    service = TradingStateService(factory)
    service.on_signal(*SCOPE, "BUY")
    service.confirm_execution(*SCOPE)
    with pytest.raises(ValueError, match="finite positive"):
        service.confirm_fill(*SCOPE, fill_price=price)
    assert service.get_state(*SCOPE)["state"] == "ENTRY_PENDING"


def test_parallel_promotions_leave_one_production_and_rollback_preserves_lineage(factory):
    registry = ParameterRegistry(factory)
    candidates = [registry.create_candidate(scope_key="AAPL", strategy_generation="A", parameters={}) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as workers:
        list(workers.map(lambda row: registry.promote_to_production(row["id"]), candidates))
    versions = registry.list_versions("AAPL", "A")
    assert sum(v["status"] == "PRODUCTION" for v in versions) == 1
    production = registry.get_production("AAPL", "A")
    parent = next(v for v in versions if v["id"] == production["parent_id"])
    restored = registry.rollback(parent["id"])
    assert restored["parent_id"] == parent["parent_id"]


def test_confirmed_event_cannot_be_downgraded_and_notified_again(factory):
    service = SignalEventService(factory)
    record, _, _ = service.record_and_notify(lambda _: True, **EVENT)
    with pytest.raises(ValueError, match="Invalid signal transition"):
        service.mark_status(record["signal_id"], "BLOCKED")
    assert service.record_decision(**EVENT, status="PREVIEW").record["status"] == "CONFIRMED"


def test_notification_exception_is_auditable_and_not_retried(factory):
    service = SignalEventService(factory)
    def failure(_):
        raise RuntimeError("delivery unavailable")
    with pytest.raises(RuntimeError, match="delivery unavailable"):
        service.record_and_notify(failure, **EVENT)
    record = service.list_recent()[0]
    assert '"error_type": "RuntimeError"' in record["details"]
    assert not service.record_and_notify(failure, **EVENT)[2]


def test_hold_does_not_send_an_actionable_notification(factory):
    event = {**EVENT, "action": "HOLD"}
    sent = []
    assert not SignalEventService(factory).record_and_notify(sent.append, **event)[2]
    assert not sent


def test_ambiguous_identity_is_rejected(factory):
    with pytest.raises(ValueError, match="identity parts"):
        SignalEventService(factory).record_decision(**{**EVENT, "strategy_version": "A|v2"})


def test_delivery_failure_does_not_revert_a_concurrent_execution(factory):
    service = SignalEventService(factory)
    def callback(record):
        service.mark_status(record["signal_id"], "EXECUTED")
        return False
    record, _, sent = service.record_and_notify(callback, **EVENT)
    stored = service.get(record["signal_id"])
    assert not sent and stored["status"] == "EXECUTED"
    assert '"status": "FAILED"' in stored["details"]
