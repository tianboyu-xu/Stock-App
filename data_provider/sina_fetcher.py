# -*- coding: utf-8 -*-
"""Sina Finance daily K-line fetcher for A-share fallback routing.

Uses Sina's CN_MarketDataService JSONP endpoint — a completely independent
backend from Eastmoney/Efinance, providing fast (~1 s) and reliable A-share
daily data without any API key.

Limitations
-----------
- A-share stocks only (sh/sz prefix).  US and HK stocks are *not* supported.
- The endpoint returns at most 1023 bars (~4 years of daily data).  If more
  is requested the call may hang or return incomplete data; we request at most
  1023 bars and let the fallback chain handle longer histories.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS, normalize_stock_code, is_bse_code

logger = logging.getLogger(__name__)

_MAX_KLINE_BARS = 1023  # Sina DailyK hard cap
_HTTP_TIMEOUT_SECONDS = 10

# ---------------------------------------------------------------------------
# Symbol helpers
# ---------------------------------------------------------------------------

def _to_sina_symbol(stock_code: str) -> str:
    """Convert a normalised 6-digit A-share code to the Sina sh/sz prefix form.

    Examples: 600519 -> sh600519, 000001 -> sz000001
    Returns empty string for non-A-share codes (HK, US, BSE, etc.).
    """
    code = normalize_stock_code(stock_code)
    if not code or not code.isdigit() or len(code) != 6:
        return ""
    # BSE (Beijing Stock Exchange) is not supported by Sina DailyK
    if is_bse_code(code):
        return ""
    if code.startswith(("6", "5", "9")):
        return f"sh{code}"
    return f"sz{code}"


def _read_sina_priority() -> int:
    raw_value = os.getenv("SINA_PRIORITY", "1")
    try:
        return int(str(raw_value).strip())
    except (TypeError, ValueError):
        logger.warning("SINA_PRIORITY=%r is not a valid integer; falling back to 1", raw_value)
        return 1


def _estimate_lookback_days(*, start_date: str, end_date: str) -> int:
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        calendar_days = max(1, (end - start).days + 1)
    except ValueError:
        calendar_days = 90
    return max(30, min(_MAX_KLINE_BARS, int(calendar_days * 1.8) + 20))


def _format_sina_date(date_str: str) -> str:
    """Ensure date string is in YYYY-MM-DD format."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _empty_daily_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=STANDARD_COLUMNS)


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class SinaFetcher(BaseFetcher):
    """Fetch daily K-line data from Sina Finance CN_MarketDataService endpoint.

    This is a fast (~1 s), free, no-API-key data source for A-share stocks.
    It uses a completely different backend from Eastmoney, making it an
    excellent fallback when Efinance/Akshare are unreachable.
    """

    name = "SinaFetcher"
    priority = _read_sina_priority()
    allow_empty_daily_data = True

    _KLINE_URL = (
        "https://quotes.sina.cn/cn/api/jsonp_v2.php"
        "/var%20_{symbol}_kline=/CN_MarketDataService.getKLineData"
    )

    # ------------------------------------------------------------------
    # BaseFetcher interface
    # ------------------------------------------------------------------

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        code = normalize_stock_code(stock_code)
        symbol = _to_sina_symbol(code)
        if not symbol:
            raise DataFetchError(
                f"SinaFetcher unsupported stock code: {stock_code} "
                "(Sina DailyK only supports A-share stocks)"
            )

        lookback = _estimate_lookback_days(start_date=start_date, end_date=end_date)
        logger.info(
            "[SinaFetcher] fetching %s symbol=%s lookback=%d start=%s end=%s",
            stock_code, symbol, lookback, start_date, end_date,
        )

        response = requests.get(
            self._KLINE_URL,
            params={
                "symbol": symbol,
                "scale": "240",       # daily
                "ma": "no",
                "datalen": str(lookback),
            },
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "*/*",
                "Referer": "https://finance.sina.com.cn",
            },
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        rows = self._parse_jsonp(response.text)
        if not rows:
            logger.info("SinaFetcher empty daily history for %s", stock_code)
            return _empty_daily_frame()

        df = pd.DataFrame(rows)

        # Filter by start_date — Sina returns the *last N bars* and does not
        # support a start_date parameter, so we trim client-side.
        if "day" in df.columns:
            df = df.rename(columns={"day": "date"})
        if "date" in df.columns:
            try:
                df["_date_dt"] = pd.to_datetime(df["date"])
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                df = df[(df["_date_dt"] >= start_dt) & (df["_date_dt"] <= end_dt)]
                df = df.drop(columns=["_date_dt"])
            except Exception:
                pass  # keep all rows if date parsing fails

        if df.empty:
            return _empty_daily_frame()

        # Ensure required columns exist
        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                df[col] = 0.0
        if "amount" not in df.columns:
            df["amount"] = 0.0

        return df

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        normalized = df.copy()
        for column in ("open", "high", "low", "close", "volume", "amount"):
            if column in normalized.columns:
                normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
        if "pct_chg" not in normalized.columns:
            normalized["pct_chg"] = normalized["close"].pct_change().fillna(0.0) * 100
        # Select standard columns (drop any extras)
        cols = [c for c in STANDARD_COLUMNS if c in normalized.columns]
        normalized = normalized[cols]
        return normalized

    # ------------------------------------------------------------------
    # JSONP parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_jsonp(text: str) -> list:
        """Extract the JSON array from Sina's JSONP wrapper.

        Expected format::

            var _sh600519_kline=([{...}, ...])

        Falls back to plain JSON parsing if the wrapper is absent.
        """
        text = text.strip()
        # Try to find the JSON array inside the JSONP callback
        match = re.search(r'\[[\s\S]*\]', text)
        if match:
            try:
                import json
                return json.loads(match.group(0))
            except Exception:
                pass
        # Fallback: try direct JSON parsing
        try:
            import json
            return json.loads(text)
        except Exception:
            logger.warning("SinaFetcher failed to parse JSONP response (len=%d)", len(text))
            return []
