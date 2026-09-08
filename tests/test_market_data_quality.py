# -*- coding: utf-8 -*-
"""Phase 3 tests: market-data quality and candle-finality gate.

Fixed US-market timestamps (verified against exchange_calendars):
- Fri 2026-09-04 12:00 ET (intraday) -> latest completed session 2026-09-03
- Fri 2026-09-04 20:00 ET (after close) -> latest completed session 2026-09-04
- Mon 2026-09-07 10:00 ET (Labor Day, closed) -> 2026-09-04
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.services.market_data_quality import (
    REASON_DATA_STALE,
    REASON_DUPLICATE_TIMESTAMP,
    REASON_EMPTY_SERIES,
    REASON_INVALID_OHLCV,
    REASON_MISSING_VOLUME,
    REASON_UNFINISHED_CANDLE,
    REASON_UNKNOWN_MARKET,
    STATUS_BLOCKED,
    STATUS_CONFIRMED,
    STATUS_PREVIEW,
    check_bars_for_signals,
)

EASTERN = ZoneInfo("America/New_York")


def _at(ts):
    return datetime.strptime(ts, "%Y-%m-%d %H:%M").replace(tzinfo=EASTERN)


def _bar(day, price=10.0, volume=1_000_000.0):
    return {
        "date": f"2026-09-{day:02d}",
        "open": price,
        "high": price + 0.06,
        "low": price - 0.06,
        "close": price,
        "volume": volume,
    }


def _series(last_day, first_day=1):
    return [_bar(d) for d in range(first_day, last_day + 1)]


def test_current_finalized_data_passes():
    report = check_bars_for_signals(
        _series(4), market="us", provider="tencent",
        adjustment_mode="none", current_time=_at("2026-09-04 20:00"),
    )
    assert report.status == STATUS_CONFIRMED
    assert report.reason is None
    assert report.actionable is True
    assert report.latest_bar_date.isoformat() == "2026-09-04"
    assert report.expected_session.isoformat() == "2026-09-04"
    meta = report.metadata()
    assert meta["provider"] == "tencent"
    assert meta["adjustment_mode"] == "none"
    assert meta["latest_bar_date"] == "2026-09-04"
    assert meta["data_status"] == STATUS_CONFIRMED


def test_stale_data_blocks():
    report = check_bars_for_signals(
        _series(3), market="us", provider="tencent", current_time=_at("2026-09-04 20:00"),
    )
    assert report.status == STATUS_BLOCKED
    assert report.reason == REASON_DATA_STALE
    assert report.actionable is False


def test_unfinished_daily_candle_is_preview_only():
    # Friday intraday: today's bar is present but the session hasn't closed.
    report = check_bars_for_signals(
        _series(4), market="us", provider="tencent", current_time=_at("2026-09-04 12:00"),
    )
    assert report.status == STATUS_PREVIEW
    assert report.reason == REASON_UNFINISHED_CANDLE
    assert report.actionable is False


def test_duplicate_latest_candle_blocks():
    bars = _series(4) + [_bar(4)]
    report = check_bars_for_signals(
        bars, market="us", provider="tencent", current_time=_at("2026-09-04 20:00"),
    )
    assert report.status == STATUS_BLOCKED
    assert report.reason == REASON_DUPLICATE_TIMESTAMP
    assert report.actionable is False


def test_missing_ohlc_blocks():
    bars = _series(4)
    del bars[-1]["close"]
    report = check_bars_for_signals(
        bars, market="us", provider="tencent", current_time=_at("2026-09-04 20:00"),
    )
    assert report.status == STATUS_BLOCKED
    assert report.reason == REASON_INVALID_OHLCV


def test_invalid_ohlc_blocks():
    bars = _series(4)
    bars[-1]["high"] = bars[-1]["low"] - 1.0  # high < low
    report = check_bars_for_signals(
        bars, market="us", provider="tencent", current_time=_at("2026-09-04 20:00"),
    )
    assert report.status == STATUS_BLOCKED
    assert report.reason == REASON_INVALID_OHLCV

    bars = _series(4)
    bars[-1]["close"] = 0  # 非正价格
    report = check_bars_for_signals(
        bars, market="us", provider="tencent", current_time=_at("2026-09-04 20:00"),
    )
    assert report.status == STATUS_BLOCKED
    assert report.reason == REASON_INVALID_OHLCV


def test_missing_volume_blocks_when_required():
    bars = _series(4)
    del bars[-1]["volume"]
    report = check_bars_for_signals(
        bars, market="us", provider="tencent", current_time=_at("2026-09-04 20:00"),
    )
    assert report.status == STATUS_BLOCKED
    assert report.reason == REASON_MISSING_VOLUME

    report = check_bars_for_signals(
        bars, market="us", provider="tencent", current_time=_at("2026-09-04 20:00"),
        require_volume=False,
    )
    assert report.status == STATUS_CONFIRMED


def test_empty_series_and_unknown_market_block():
    report = check_bars_for_signals([], market="us", provider="tencent")
    assert report.status == STATUS_BLOCKED
    assert report.reason == REASON_EMPTY_SERIES

    report = check_bars_for_signals(
        _series(4), market=None, provider="tencent", current_time=_at("2026-09-04 20:00"),
    )
    assert report.status == STATUS_BLOCKED
    assert report.reason == REASON_UNKNOWN_MARKET


def test_holiday_session_still_validates():
    # Labor Day Monday: Friday's bar remains the latest completed session.
    report = check_bars_for_signals(
        _series(4), market="us", provider="tencent", current_time=_at("2026-09-07 10:00"),
    )
    assert report.status == STATUS_CONFIRMED
    assert report.expected_session.isoformat() == "2026-09-04"
