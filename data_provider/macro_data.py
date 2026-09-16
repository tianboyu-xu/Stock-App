"""Point-in-time ALFRED macro snapshots for the quarterly trigger router.

FRED's default historical values are revised. Requests here explicitly retrieve
real-time intervals, then select only the version visible on the decision date.
ALFRED availability dates have daily (not intraday release-time) precision.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
from statistics import fmean
import tempfile
from typing import Any, Sequence

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.core.trading_calendar import get_effective_trading_date, get_market_now


SNAPSHOT_VERSION = 1
FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
# Each tuple is feature, series, transform, native frequency, maximum age in days.
# RSXFS is total retail and food services sales, not the retail control group.
FEATURE_SPECS = (
    ("industrial_production_3m", "INDPRO", "pct3", "monthly", 100),
    ("retail_sales_3m", "RSXFS", "pct3", "monthly", 100),
    ("real_gdp_qoq", "GDPC1", "pct1", "quarterly", 210),
    ("payrolls_3m", "PAYEMS", "pct3", "monthly", 100),
    ("unemployment_change_3m", "UNRATE", "diff3", "monthly", 100),
    ("initial_claims_4w_change", "ICSA", "weekly_change", "weekly", 30),
    ("continuing_claims_4w_change", "CCSA", "weekly_change", "weekly", 40),
    ("core_cpi_3m_annualized", "CPILFESL", "annualized3", "monthly", 100),
    ("core_pce_3m_annualized", "PCEPILFE", "annualized3", "monthly", 110),
    ("wage_growth_3m_annualized", "CES0500000003", "annualized3", "monthly", 100),
    ("fed_funds_change_3m", "FEDFUNDS", "diff3", "monthly", 100),
    ("treasury_2y_change_3m", "DGS2", "daily_diff3", "daily", 14),
    ("real_yield_10y_change_3m", "DFII10", "daily_diff3", "daily", 14),
    ("yield_curve_2s10s", "T10Y2Y", "level", "daily", 14),
    ("high_yield_spread_change_3m", "BAMLH0A0HYM2", "daily_diff3", "daily", 14),
)


class MacroDataError(RuntimeError):
    """A macro result cannot be constructed safely."""


class MacroConfigurationError(MacroDataError):
    """The optional vintage provider has not been configured."""


class MacroDataUnavailable(MacroDataError):
    """The provider or trading calendar cannot supply the required history."""


class MacroVintageUnavailable(MacroDataUnavailable):
    """FRED explicitly reports no ALFRED vintages in this requested interval."""


class MacroSnapshotIntegrityError(MacroDataError):
    """An existing immutable snapshot is invalid; it must not be overwritten."""


def quarter_for_date(value: date) -> str:
    return f"{value.year}Q{(value.month - 1) // 3 + 1}"


def quarter_start(quarter: str) -> date:
    match = re.fullmatch(r"(\d{4})Q([1-4])", str(quarter))
    if not match:
        raise ValueError("Quarter must have the form YYYYQ1 through YYYYQ4")
    return date(int(match[1]), (int(match[2]) - 1) * 3 + 1, 1)


def quarter_decision_date(quarter: str) -> date:
    """Last completed NYSE session before the quarter, with no weekday fallback."""
    previous_day = quarter_start(quarter) - timedelta(days=1)
    try:
        return get_effective_trading_date(
            "us", datetime.combine(previous_day, time.max), strict=True,
        )
    except (RuntimeError, ValueError) as exc:
        raise MacroDataUnavailable("NYSE calendar unavailable for macro decision date") from exc


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def freeze_json(path: str | Path, data: dict[str, Any]) -> dict[str, Any]:
    """Atomically publish a JSON file once; return the first writer's contents.

    A temporary file plus an exclusive hard-link avoids both partial reads and
    replacing a competing writer's already-frozen quarterly decision.
    """
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False,
                ) as handle:
                    temp_path = Path(handle.name)
                    handle.write(_canonical_json(data))
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(temp_path, path)
                except FileExistsError:
                    pass
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
    except OSError as exc:
        raise MacroDataUnavailable("Cannot persist immutable macro data in MATR_DATA_DIR") from exc
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Expected JSON object")
        return payload
    except (OSError, ValueError) as exc:
        raise MacroSnapshotIntegrityError("Existing frozen macro data is unreadable") from exc


@dataclass(frozen=True)
class MacroSnapshot:
    quarter: str
    decision_date: str
    features: dict[str, float]
    factor_scores: dict[str, float]
    regime: str
    observations: dict[str, list[dict[str, Any]]]
    missing_features: tuple[str, ...]
    snapshot_id: str
    schema_version: int = SNAPSHOT_VERSION
    source: str = "ALFRED real-time intervals (daily availability)"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["missing_features"] = list(self.missing_features)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MacroSnapshot:
        try:
            values = dict(data)
            snapshot_id = values.pop("snapshot_id")
            if hashlib.sha256(_canonical_json(values).encode()).hexdigest() != snapshot_id:
                raise ValueError("Snapshot checksum mismatch")
            if values["schema_version"] != SNAPSHOT_VERSION:
                raise ValueError("Unsupported snapshot version")
            values["missing_features"] = tuple(values["missing_features"])
            snapshot = cls(snapshot_id=snapshot_id, **values)
            if snapshot.decision_date != quarter_decision_date(snapshot.quarter).isoformat():
                raise ValueError("Snapshot decision date is inconsistent with NYSE calendar")
            for rows in snapshot.observations.values():
                for row in rows:
                    if max(row["observation_date"], row["vintage_date"]) > snapshot.decision_date:
                        raise ValueError("Snapshot contains unavailable observations")
            return snapshot
        except (KeyError, TypeError, ValueError) as exc:
            raise MacroSnapshotIntegrityError("Frozen macro snapshot failed validation") from exc


def _visible_observations(rows: list[dict[str, Any]], as_of: date) -> list[dict[str, Any]]:
    cutoff = as_of.isoformat()
    earliest = (pd.Timestamp(as_of) - pd.DateOffset(months=18)).date().isoformat()
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if earliest <= row["date"] <= cutoff and row["realtime_start"] <= cutoff:
            by_date.setdefault(row["date"], []).append(row)
    result = []
    for observation_date, versions in sorted(by_date.items()):
        versions.sort(key=lambda row: row["realtime_start"])
        candidates = [row for row in versions if row["realtime_end"] >= cutoff]
        if not candidates:
            continue
        latest = candidates[-1]
        # A missing value in the current vintage must not resurrect an older value.
        if latest["value"] is None:
            continue
        initial = next((row for row in versions if row["value"] is not None), latest)
        result.append({
            "observation_date": observation_date,
            "release_date": initial["realtime_start"],
            "value_at_release": initial["value"],
            "vintage_date": latest["realtime_start"],
            "revision_date": (
                latest["realtime_start"] if latest["realtime_start"] != initial["realtime_start"] else None
            ),
            "value": latest["value"],
        })
    return result


def _period_value(rows: list[dict[str, Any]], months: int) -> float | None:
    last = pd.Timestamp(rows[-1]["observation_date"])
    target = (last - pd.DateOffset(months=months)).date().isoformat()
    found = next((row for row in reversed(rows) if row["observation_date"] <= target), None)
    # Monthly/quarterly series dates are period starts, so missing periods are
    # rejected rather than silently changing a three-month feature to six months.
    if found is None or found["observation_date"] != target:
        return None
    return found["value"]


def _feature_value(rows: list[dict[str, Any]], transform: str, frequency: str) -> float | None:
    if not rows:
        return None
    latest = rows[-1]["value"]
    if transform == "level":
        return latest
    if transform == "weekly_change":
        if len(rows) < 8:
            return None
        recent = rows[-8:]
        gaps = [
            (date.fromisoformat(right["observation_date"]) - date.fromisoformat(left["observation_date"])).days
            for left, right in zip(recent, recent[1:])
        ]
        if any(gap != 7 for gap in gaps):
            return None
        base = fmean(row["value"] for row in recent[:4])
        return 100.0 * (fmean(row["value"] for row in recent[4:]) / base - 1) if base > 0 else None
    if transform == "daily_diff3":
        target = (pd.Timestamp(rows[-1]["observation_date"]) - pd.DateOffset(months=3)).date()
        previous = next((row for row in reversed(rows) if row["observation_date"] <= target.isoformat()), None)
        if previous is None or (target - date.fromisoformat(previous["observation_date"])).days > 7:
            return None
        return latest - previous["value"]
    months = 3 if transform != "pct1" or frequency == "quarterly" else 1
    base = _period_value(rows, months)
    if base is None:
        return None
    if transform == "diff3":
        return latest - base
    if base <= 0 or latest <= 0:
        return None
    exponent = 4 if transform == "annualized3" else 1
    return 100.0 * ((latest / base) ** exponent - 1)


def _factor_scores(features: dict[str, float], observations: dict[str, list[dict[str, Any]]]) -> dict[str, float]:
    groups = {
        "growth": (("industrial_production_3m", 2.0), ("retail_sales_3m", 3.0), ("real_gdp_qoq", 1.0)),
        "labor": (("payrolls_3m", 0.6), ("unemployment_change_3m", -0.5),
                  ("initial_claims_4w_change", -10.0), ("continuing_claims_4w_change", -10.0)),
        "liquidity": (("fed_funds_change_3m", -1.0), ("treasury_2y_change_3m", -1.0),
                      ("real_yield_10y_change_3m", -0.5), ("high_yield_spread_change_3m", -1.0)),
    }
    scores = {}
    for group, members in groups.items():
        values = [math.tanh(features[key] / scale) for key, scale in members if key in features]
        if values:
            scores[group] = round(fmean(values), 6)
    inflation = []
    for key, series in (("core_cpi_3m_annualized", "CPILFESL"), ("core_pce_3m_annualized", "PCEPILFE")):
        rows = observations.get(series, [])
        if key not in features or not rows:
            continue
        cutoff = (pd.Timestamp(rows[-1]["observation_date"]) - pd.DateOffset(months=3)).date().isoformat()
        preceding = [row for row in rows if row["observation_date"] <= cutoff]
        previous = _feature_value(preceding, "annualized3", "monthly")
        if previous is not None:
            inflation.append(math.tanh((features[key] - previous) / 2.0))
    if inflation:
        scores["inflation"] = round(fmean(inflation), 6)
    return scores


def build_snapshot(quarter: str, histories: dict[str, list[dict[str, Any]]]) -> MacroSnapshot:
    """Build a raw feature vector solely from intervals visible at quarter start."""
    decision = quarter_decision_date(quarter)
    observations = {series: _visible_observations(rows, decision) for series, rows in histories.items()}
    features: dict[str, float] = {}
    for key, series, transform, frequency, max_age in FEATURE_SPECS:
        rows = observations.get(series, [])
        if not rows or (decision - date.fromisoformat(rows[-1]["observation_date"])).days > max_age:
            continue
        value = _feature_value(rows, transform, frequency)
        if value is not None and math.isfinite(value):
            features[key] = round(value, 8)
    if not features:
        raise MacroDataUnavailable(f"No point-in-time macro features available for {quarter}")
    scores = _factor_scores(features, observations)
    regime = "Unknown"
    if "growth" in scores and "inflation" in scores:
        regime = {
            (True, False): "Goldilocks", (True, True): "Reflation",
            (False, False): "Slowdown", (False, True): "Stagflation",
        }[(scores["growth"] >= 0, scores["inflation"] > 0)]
    snapshot = MacroSnapshot(
        quarter=quarter, decision_date=decision.isoformat(), features=features,
        factor_scores=scores, regime=regime, observations=observations,
        missing_features=tuple(spec[0] for spec in FEATURE_SPECS if spec[0] not in features), snapshot_id="",
    )
    payload = snapshot.to_dict()
    payload.pop("snapshot_id")
    payload["snapshot_id"] = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
    return MacroSnapshot.from_dict(payload)


class MacroDataProvider:
    """Fetch each series once for a batch of quarters and freeze local snapshots."""

    def __init__(
        self, api_key: str | None, cache_dir: str | Path, *, timeout: float = 15.0,
        retries: int = 2, session: requests.Session | None = None,
    ):
        self.api_key = (api_key or "").strip()
        self.cache_dir = Path(cache_dir)
        self.timeout = float(timeout)
        if not math.isfinite(self.timeout) or self.timeout <= 0 or retries < 0:
            raise ValueError("Macro request timeout must be positive and retries nonnegative")
        self.session = session or requests.Session()
        if session is None:
            retry = Retry(
                total=int(retries), backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET"}), respect_retry_after_header=False,
            )
            self.session.mount("https://", HTTPAdapter(max_retries=retry))

    @classmethod
    def from_config(cls, config: Any = None) -> MacroDataProvider:
        if config is None:
            from src.config import get_config
            config = get_config()
        return cls(
            config.fred_api_key, config.matr_data_dir or Path(config.database_path).parent / "matr",
            timeout=config.matr_request_timeout_seconds, retries=config.matr_request_retries,
        )

    def get_snapshot(self, quarter: str) -> MacroSnapshot:
        return self.get_snapshots([quarter])[quarter]

    def get_snapshots(self, quarters: Sequence[str]) -> dict[str, MacroSnapshot]:
        ordered = sorted(set(quarters), key=quarter_start)
        if not ordered:
            return {}
        now = get_market_now("us").date()
        if any(quarter_decision_date(quarter) >= now for quarter in ordered):
            raise MacroDataUnavailable("Quarter decision date is not yet complete")
        result: dict[str, MacroSnapshot] = {}
        missing = []
        for quarter in ordered:
            path = self._snapshot_path(quarter)
            if path.exists():
                snapshot = MacroSnapshot.from_dict(freeze_json(path, {}))
                if snapshot.quarter != quarter:
                    raise MacroSnapshotIntegrityError("Cached macro quarter does not match its filename")
                result[quarter] = snapshot
            else:
                missing.append(quarter)
        if missing:
            if not self.api_key:
                raise MacroConfigurationError("Configure FRED_API_KEY to enable MATR vintage data")
            first = quarter_decision_date(missing[0])
            last = quarter_decision_date(missing[-1])
            start = (pd.Timestamp(first) - pd.DateOffset(months=18)).date()
            histories = {
                spec[1]: self._fetch_series(spec[1], start, last)
                for spec in FEATURE_SPECS
            }
            for quarter in missing:
                snapshot = build_snapshot(quarter, histories)
                result[quarter] = MacroSnapshot.from_dict(freeze_json(self._snapshot_path(quarter), snapshot.to_dict()))
        return {quarter: result[quarter] for quarter in ordered}

    def _snapshot_path(self, quarter: str) -> Path:
        quarter_start(quarter)
        return self.cache_dir / f"v{SNAPSHOT_VERSION}" / f"macro_snapshot_{quarter}.json"

    def _fetch_series(self, series: str, observation_start: date, as_of: date) -> list[dict[str, Any]]:
        # FRED JSON permits <=2,000 vintage dates, independent of observation
        # filters. These realized series cannot predate their observation dates.
        rows = []
        begin = observation_start
        while begin <= as_of:
            end = min(as_of, begin + timedelta(days=1460))
            try:
                rows.extend(self._fetch_intervals(series, observation_start, begin, end))
            except MacroVintageUnavailable:
                # Explicit absence becomes missing_features in affected snapshots.
                # Never follow the API's suggestion to request today's revision.
                pass
            begin = end + timedelta(days=1)
        merged = []
        for row in sorted(rows, key=lambda item: (item["date"], item["realtime_start"])):
            if (merged and merged[-1]["date"] == row["date"] and merged[-1]["value"] == row["value"]
                    and date.fromisoformat(row["realtime_start"]) <=
                    date.fromisoformat(merged[-1]["realtime_end"]) + timedelta(days=1)):
                merged[-1]["realtime_end"] = max(merged[-1]["realtime_end"], row["realtime_end"])
            else:
                merged.append(dict(row))
        return merged

    def _fetch_intervals(self, series: str, observation_start: date,
                         realtime_start: date, as_of: date) -> list[dict[str, Any]]:
        params = {
            "api_key": self.api_key, "series_id": series, "file_type": "json", "output_type": 1,
            "realtime_start": realtime_start.isoformat(), "realtime_end": as_of.isoformat(),
            "observation_start": observation_start.isoformat(), "observation_end": as_of.isoformat(),
            "sort_order": "asc", "limit": 100000, "offset": 0,
        }
        rows = []
        while True:
            try:
                response = self.session.get(FRED_OBSERVATIONS_URL, params=params, timeout=self.timeout)
                if response.status_code == 400:
                    failure = response.json()
                    if "series does not exist in ALFRED" in str(failure.get("error_message", "")):
                        raise MacroVintageUnavailable(f"No ALFRED vintage for {series} in requested interval")
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                # Requests exceptions include the request URL and API key. Never
                # expose them in the message or exception chain sent to callers.
                status = getattr(getattr(exc, "response", None), "status_code", None)
                detail = f"HTTP {status}" if status is not None else type(exc).__name__
                raise MacroDataUnavailable(f"ALFRED request failed for {series} ({detail})") from None
            try:
                if payload.get("output_type") != 1:
                    raise ValueError("ALFRED did not return real-time intervals")
                if payload.get("realtime_start") != params["realtime_start"]:
                    raise ValueError("ALFRED real-time start mismatch")
                if payload.get("realtime_end") != as_of.isoformat():
                    raise ValueError("ALFRED real-time end mismatch")
                page = payload["observations"]
                count = int(payload["count"])
                if not isinstance(page, list) or count < 0:
                    raise ValueError("Invalid observations")
                for row in page:
                    observed = date.fromisoformat(row["date"]).isoformat()
                    vintage = date.fromisoformat(row["realtime_start"]).isoformat()
                    end = date.fromisoformat(row["realtime_end"]).isoformat()
                    if vintage > end or vintage > as_of.isoformat() or observed > as_of.isoformat():
                        raise ValueError("Invalid real-time interval")
                    value = None if row["value"] == "." else float(row["value"])
                    if value is not None and not math.isfinite(value):
                        raise ValueError("Nonfinite macro observation")
                    rows.append({"date": observed, "realtime_start": vintage, "realtime_end": end, "value": value})
                params["offset"] += len(page)
                if params["offset"] >= count:
                    break
                if not page:
                    raise ValueError("Incomplete ALFRED response")
            except (AttributeError, KeyError, TypeError, ValueError):
                raise MacroDataUnavailable(f"Invalid ALFRED vintage response for {series}") from None
        return rows
