# -*- coding: utf-8 -*-
"""
行情数据质量门禁（Market Data Quality）
======================================

可执行信号在进入策略引擎之前必须通过本检查：

1. **新鲜度（Freshness）**：最新一根 bar 的日期必须等于该市场
   “最近一个已收盘交易日”（``get_effective_trading_date``）。
   缺失则判定 ``DATA_STALE`` 并阻止可执行信号。
2. **K 线完结性（Finality）**：当日盘中 bar（日期晚于已收盘交易日）
   只能产生 ``PREVIEW`` 信号，不得作为可执行信号。
3. **OHLCV 合法性**：缺失开/收、high < low、非正价格、缺失成交量
   （可配置）、重复时间戳一律阻止。
4. **元数据留存**：每个结论保留 provider、最新 bar 日期、
   复权模式与新鲜度状态，供 SignalEvent 复现（Rule 8）。

复权政策（显式声明）：
- 指标与执行目前消费同一套 provider 日线序列；
- ``adjustment_mode`` 由调用方按 provider/配置声明（如 TickFlow 的
  ``TICKFLOW_KLINE_ADJUST``，默认 ``none``），未知时记为 ``unknown``，
  不做隐式假设；
- provider 名称必须随信号记录，不得对可执行信号静默切换数据源（Rule 3）。

本模块只做判定，不拉取行情（可测、确定性；时间通过 ``current_time``
注入）。
"""

from __future__ import annotations

from math import isfinite
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.core.trading_calendar import MARKET_EXCHANGE, get_effective_trading_date

# 结论状态
STATUS_CONFIRMED = "CONFIRMED"  # 数据新鲜且末 bar 已完结，可执行
STATUS_PREVIEW = "PREVIEW"  # 末 bar 是当日未完结 K 线，仅可预览
STATUS_BLOCKED = "BLOCKED"  # 阻止可执行信号

# 阻止原因码
REASON_DATA_STALE = "DATA_STALE"
REASON_UNFINISHED_CANDLE = "UNFINISHED_CANDLE"
REASON_INVALID_OHLCV = "INVALID_OHLCV"
REASON_MISSING_VOLUME = "MISSING_VOLUME"
REASON_DUPLICATE_TIMESTAMP = "DUPLICATE_TIMESTAMP"
REASON_UNKNOWN_MARKET = "UNKNOWN_MARKET"
REASON_CALENDAR_UNAVAILABLE = "CALENDAR_UNAVAILABLE"
REASON_EMPTY_SERIES = "EMPTY_SERIES"


@dataclass(frozen=True)
class BarQualityIssue:
    """单根 bar 的质量问题。"""

    index: int
    bar_date: Optional[str]
    reason: str
    detail: str


@dataclass(frozen=True)
class MarketDataQualityReport:
    """数据质量判定结论（可直接写入 SignalEvent 复现元数据）。"""

    status: str  # CONFIRMED / PREVIEW / BLOCKED
    reason: Optional[str]  # BLOCKED/PREVIEW 的原因码，CONFIRMED 为 None
    market: Optional[str]
    provider: Optional[str]
    adjustment_mode: str
    latest_bar_date: Optional[date]
    expected_session: Optional[date]
    issues: List[BarQualityIssue] = field(default_factory=list)
    checked_bars: int = 0

    @property
    def actionable(self) -> bool:
        """只有 CONFIRMED 允许产生可执行信号。"""
        return self.status == STATUS_CONFIRMED

    def metadata(self) -> Dict[str, Any]:
        """SignalEvent 复现所需的最小元数据（Rule 8）。"""
        return {
            "provider": self.provider,
            "adjustment_mode": self.adjustment_mode,
            "latest_bar_date": (
                self.latest_bar_date.isoformat() if self.latest_bar_date else None
            ),
            "expected_session": (
                self.expected_session.isoformat() if self.expected_session else None
            ),
            "data_status": self.status,
            "data_reason": self.reason,
        }


def _parse_bar_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None


def _parse_price(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number):
        return None
    return number


def check_bars_for_signals(
    bars: Sequence[Mapping[str, Any]],
    *,
    market: Optional[str],
    provider: Optional[str] = None,
    adjustment_mode: Optional[str] = None,
    current_time: Optional[datetime] = None,
    require_volume: bool = True,
) -> MarketDataQualityReport:
    """判定一组日线 bar 是否可用于生成可执行信号。

    Args:
        bars: 升序 K 线序列（date/open/high/low/close/volume）。
        market: 'cn' | 'hk' | 'us' | 'jp' | 'kr' | 'tw'；未知则直接阻止。
        provider: 数据源名称（原样记录，不做校验）。
        adjustment_mode: 复权模式声明；未知记为 ``unknown``。
        current_time: 注入“现在”（测试用）；None 则取市场当地时间。
        require_volume: 是否要求成交量存在且为数值。
    """
    mode = (adjustment_mode or "").strip() or "unknown"

    def blocked(reason: str, issues: List[BarQualityIssue]) -> MarketDataQualityReport:
        return MarketDataQualityReport(
            status=STATUS_BLOCKED,
            reason=reason,
            market=market,
            provider=provider,
            adjustment_mode=mode,
            latest_bar_date=_latest_date(bars),
            expected_session=None,
            issues=issues,
            checked_bars=len(bars),
        )

    if not bars:
        return blocked(REASON_EMPTY_SERIES, [])

    normalized_market = (market or "").strip().lower()
    if normalized_market not in MARKET_EXCHANGE:
        return blocked(
            REASON_UNKNOWN_MARKET,
            [BarQualityIssue(-1, None, REASON_UNKNOWN_MARKET, "market 未指定，无法核验新鲜度")],
        )

    issues: List[BarQualityIssue] = []
    seen: Dict[str, int] = {}
    bar_dates: List[Optional[date]] = []
    for index, bar in enumerate(bars):
        raw_date = bar.get("date")
        bar_date = _parse_bar_date(raw_date)
        bar_dates.append(bar_date)
        date_text = bar_date.isoformat() if bar_date else (None if raw_date is None else str(raw_date))

        if bar_date is None:
            issues.append(BarQualityIssue(index, date_text, REASON_INVALID_OHLCV, "bar 日期缺失或无法解析"))
            continue
        if date_text in seen:
            issues.append(BarQualityIssue(
                index, date_text, REASON_DUPLICATE_TIMESTAMP,
                f"与第 {seen[date_text]} 根 bar 时间戳重复",
            ))
        else:
            seen[date_text] = index

        if index and bar_dates[index - 1] is not None and bar_date < bar_dates[index - 1]:
            issues.append(BarQualityIssue(index, date_text, REASON_INVALID_OHLCV, "bar 日期必须升序"))

        open_ = _parse_price(bar.get("open"))
        high = _parse_price(bar.get("high"))
        low = _parse_price(bar.get("low"))
        close = _parse_price(bar.get("close"))
        if open_ is None or close is None:
            issues.append(BarQualityIssue(index, date_text, REASON_INVALID_OHLCV, "open/close 缺失或非数值"))
            continue
        if high is None or low is None:
            issues.append(BarQualityIssue(index, date_text, REASON_INVALID_OHLCV, "high/low 缺失或非数值"))
            continue
        if min(open_, high, low, close) <= 0:
            issues.append(BarQualityIssue(index, date_text, REASON_INVALID_OHLCV, "价格必须为正数"))
            continue
        if not low <= min(open_, close) <= max(open_, close) <= high:
            issues.append(BarQualityIssue(index, date_text, REASON_INVALID_OHLCV, f"high({high}) < low({low})"))
            continue
        if require_volume:
            volume = _parse_price(bar.get("volume"))
            if volume is None or volume < 0:
                issues.append(BarQualityIssue(index, date_text, REASON_MISSING_VOLUME, "volume 缺失或非数值"))
                continue

    fatal = [issue for issue in issues if issue.reason != REASON_DUPLICATE_TIMESTAMP]
    duplicates = [issue for issue in issues if issue.reason == REASON_DUPLICATE_TIMESTAMP]
    if fatal:
        first = fatal[0]
        return blocked(first.reason, issues)
    if duplicates:
        return blocked(REASON_DUPLICATE_TIMESTAMP, issues)

    try:
        expected = get_effective_trading_date(normalized_market, current_time=current_time, strict=True)
    except (RuntimeError, ValueError):
        return blocked(REASON_CALENDAR_UNAVAILABLE, [])
    latest = bar_dates[-1]
    assert latest is not None  # 空日期已在上一步阻止
    if latest < expected:
        return MarketDataQualityReport(
            status=STATUS_BLOCKED,
            reason=REASON_DATA_STALE,
            market=normalized_market,
            provider=provider,
            adjustment_mode=mode,
            latest_bar_date=latest,
            expected_session=expected,
            issues=[
                BarQualityIssue(
                    len(bars) - 1, latest.isoformat(), REASON_DATA_STALE,
                    f"最新 bar({latest.isoformat()}) 早于已收盘交易日({expected.isoformat()})",
                )
            ],
            checked_bars=len(bars),
        )
    if latest > expected:
        # 最新 bar 是当日未完结 K 线：只允许 PREVIEW。
        return MarketDataQualityReport(
            status=STATUS_PREVIEW,
            reason=REASON_UNFINISHED_CANDLE,
            market=normalized_market,
            provider=provider,
            adjustment_mode=mode,
            latest_bar_date=latest,
            expected_session=expected,
            issues=[
                BarQualityIssue(
                    len(bars) - 1, latest.isoformat(), REASON_UNFINISHED_CANDLE,
                    f"最新 bar({latest.isoformat()}) 晚于已收盘交易日({expected.isoformat()})，当日 K 线未完结",
                )
            ],
            checked_bars=len(bars),
        )
    return MarketDataQualityReport(
        status=STATUS_CONFIRMED,
        reason=None,
        market=normalized_market,
        provider=provider,
        adjustment_mode=mode,
        latest_bar_date=latest,
        expected_session=expected,
        issues=[],
        checked_bars=len(bars),
    )


def _latest_date(bars: Sequence[Mapping[str, Any]]) -> Optional[date]:
    for bar in reversed(bars):
        parsed = _parse_bar_date(bar.get("date"))
        if parsed is not None:
            return parsed
    return None
