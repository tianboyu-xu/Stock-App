"""Deterministic ALFRED vintage, calendar and immutable snapshot regressions."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest
import requests

from data_provider.macro_data import (
    FEATURE_SPECS,
    MacroConfigurationError,
    MacroDataProvider,
    MacroDataUnavailable,
    MacroSnapshot,
    MacroSnapshotIntegrityError,
    build_snapshot,
    freeze_json,
    quarter_decision_date,
    quarter_for_date,
    quarter_start,
)


def _row(observed, value, release=None, end="9999-12-31"):
    return {
        "date": str(observed), "value": value,
        "realtime_start": str(release or observed), "realtime_end": end,
    }


def _histories():
    histories = {}
    for _, series, _, frequency, _ in FEATURE_SPECS:
        dates = pd.date_range(
            "2022-01-01", "2024-06-28",
            freq={"monthly": "MS", "quarterly": "QS", "weekly": "W-SAT", "daily": "B"}[frequency],
        )
        lag = {"monthly": 40, "quarterly": 110, "weekly": 5, "daily": 1}[frequency]
        histories[series] = [
            _row(d.date(), 100 + index * 0.2, d.date() + timedelta(days=lag))
            for index, d in enumerate(dates)
        ]
    return histories


def _payload(rows, as_of, *, count=None, realtime_start="2023-01-01"):
    return {
        "output_type": 1, "realtime_start": realtime_start, "realtime_end": as_of,
        "count": len(rows) if count is None else count,
        "observations": [dict(row, value="." if row["value"] is None else str(row["value"])) for row in rows],
    }


def _session(histories):
    session = Mock(spec=requests.Session)

    def get(_url, *, params, timeout):
        rows = [
            row for row in histories[params["series_id"]]
            if row["realtime_start"] <= params["realtime_end"] and row["date"] <= params["observation_end"]
        ]
        response = Mock()
        response.json.return_value = _payload(rows, params["realtime_end"], realtime_start=params["realtime_start"])
        return response

    session.get.side_effect = get
    return session


def test_quarter_boundary_uses_nyse_holidays_and_weekends():
    # Good Friday 2024 fell on March 29; June ended on a weekend.
    assert quarter_decision_date("2024Q2") == date(2024, 3, 28)
    assert quarter_decision_date("2024Q3") == date(2024, 6, 28)
    assert quarter_start("2024Q4") == date(2024, 10, 1)
    assert quarter_for_date(date(2024, 12, 31)) == "2024Q4"
    with pytest.raises(ValueError):
        quarter_start("../../2024Q2")


def test_calendar_unavailable_does_not_guess_a_weekday(monkeypatch):
    monkeypatch.setattr("src.core.trading_calendar._XCALS_AVAILABLE", False)
    with pytest.raises(MacroDataUnavailable, match="NYSE calendar"):
        quarter_decision_date("2024Q2")


def test_build_snapshot_uses_available_gdp_and_revisions_only():
    histories = _histories()
    original = next(row for row in histories["PAYEMS"] if row["date"] == "2024-02-01")
    original["realtime_end"] = "2024-05-01"
    histories["PAYEMS"].append(_row("2024-02-01", 150, "2024-05-02"))
    q2 = build_snapshot("2024Q2", histories)
    q3 = build_snapshot("2024Q3", histories)
    q2_payroll = next(row for row in q2.observations["PAYEMS"] if row["observation_date"] == "2024-02-01")
    q3_payroll = next(row for row in q3.observations["PAYEMS"] if row["observation_date"] == "2024-02-01")
    assert q2_payroll["value"] == original["value"]
    assert q2_payroll["revision_date"] is None
    assert q3_payroll["value"] == 150
    assert q3_payroll["value_at_release"] == original["value"]
    assert q3_payroll["revision_date"] == "2024-05-02"
    assert q2.observations["GDPC1"][-1]["observation_date"] == "2023-10-01"
    assert q3.observations["GDPC1"][-1]["observation_date"] == "2024-01-01"
    assert len(q2.features) == 15
    assert len(q2.factor_scores) == 4
    assert all(-1 <= value <= 1 for value in q2.factor_scores.values())
    assert MacroSnapshot.from_dict(q2.to_dict()) == q2


def test_future_revisions_do_not_change_past_snapshot_or_feature_vector():
    histories = _histories()
    before = build_snapshot("2024Q2", histories)
    histories["CPILFESL"].append(_row("2024-02-01", 99999, "2025-01-01"))
    histories["PAYEMS"].append(_row("2025-01-01", 99999, "2025-02-01"))
    assert build_snapshot("2024Q2", histories) == before


def test_missing_current_vintage_does_not_resurrect_old_value():
    histories = _histories()
    original = next(row for row in histories["PAYEMS"] if row["date"] == "2024-02-01")
    original["realtime_end"] = "2024-03-19"
    histories["PAYEMS"].append(_row("2024-02-01", None, "2024-03-20"))
    snapshot = build_snapshot("2024Q2", histories)
    assert all(row["observation_date"] != "2024-02-01" for row in snapshot.observations["PAYEMS"])


def test_missing_and_stale_series_are_explicit_without_revised_fallback():
    histories = _histories()
    histories["CPILFESL"] = []
    histories["PCEPILFE"] = []
    histories["GDPC1"] = [row for row in histories["GDPC1"] if row["date"] < "2023-01-01"]
    snapshot = build_snapshot("2024Q2", histories)
    assert "core_cpi_3m_annualized" in snapshot.missing_features
    assert "real_gdp_qoq" in snapshot.missing_features
    assert snapshot.regime == "Unknown"
    assert "inflation" not in snapshot.factor_scores
    with pytest.raises(MacroDataUnavailable, match="No point-in-time"):
        build_snapshot("2024Q2", {})


def test_monthly_features_reject_missing_comparison_period():
    histories = _histories()
    histories["INDPRO"] = [row for row in histories["INDPRO"] if row["date"] != "2023-11-01"]
    snapshot = build_snapshot("2024Q2", histories)
    assert "industrial_production_3m" in snapshot.missing_features


def test_batch_fetches_series_once_and_frozen_cache_works_without_api_key(tmp_path):
    session = _session(_histories())
    provider = MacroDataProvider("dummy-unit-test-key", tmp_path, session=session)
    snapshots = provider.get_snapshots(["2024Q3", "2024Q2", "2024Q2"])
    assert list(snapshots) == ["2024Q2", "2024Q3"]
    assert session.get.call_count == len(FEATURE_SPECS)
    for call in session.get.call_args_list:
        assert call.kwargs["params"]["realtime_start"] == "2022-09-28"
        assert call.kwargs["params"]["realtime_end"] == "2024-06-28"
        assert call.kwargs["timeout"] == 15
    reader_session = Mock(spec=requests.Session)
    reader = MacroDataProvider(None, tmp_path, session=reader_session)
    assert reader.get_snapshots(["2024Q2", "2024Q3"]) == snapshots
    reader_session.get.assert_not_called()
    with pytest.raises(MacroConfigurationError, match="FRED_API_KEY"):
        reader.get_snapshot("2024Q1")
    assert "dummy-unit-test-key" not in (tmp_path / "v1" / "macro_snapshot_2024Q2.json").read_text()


def test_pagination_preserves_every_vintage(tmp_path):
    rows = [_row("2024-01-01", 100, "2024-02-01"), _row("2024-02-01", 101, "2024-03-01")]
    session = Mock(spec=requests.Session)
    params_seen = []

    def get(_url, *, params, timeout):
        params_seen.append(deepcopy(params))
        offset = params["offset"]
        response = Mock()
        response.json.return_value = _payload(rows[offset:offset + 1], "2024-03-28", count=2)
        return response

    session.get.side_effect = get
    provider = MacroDataProvider("key", tmp_path, session=session)
    assert provider._fetch_series("TEST", date(2023, 1, 1), date(2024, 3, 28)) == rows
    assert [params["offset"] for params in params_seen] == [0, 1]


def test_long_daily_vintages_are_bounded_and_unchanged_boundary_is_not_a_revision(tmp_path):
    session = Mock(spec=requests.Session)
    seen = []

    def get(_url, *, params, timeout):
        seen.append(deepcopy(params))
        start, end = params["realtime_start"], params["realtime_end"]
        assert (date.fromisoformat(end) - date.fromisoformat(start)).days < 2000
        rows = [_row("2015-01-01", 100, max(start, "2015-02-01"), end)]
        response = Mock()
        response.json.return_value = _payload(rows, end, realtime_start=start)
        return response

    session.get.side_effect = get
    provider = MacroDataProvider("key", tmp_path, session=session)
    rows = provider._fetch_series("DGS2", date(2015, 1, 1), date(2026, 6, 30))
    assert len(seen) == 3
    assert rows == [_row("2015-01-01", 100., "2015-02-01", "2026-06-30")]
    assert seen[1]["realtime_start"] == (date.fromisoformat(seen[0]["realtime_end"]) + timedelta(days=1)).isoformat()


def test_explicit_missing_vintage_interval_is_missing_not_current_revision_fallback(tmp_path):
    session = Mock(spec=requests.Session)
    seen = []

    def get(_url, *, params, timeout):
        seen.append(deepcopy(params))
        response = Mock()
        if len(seen) == 1:
            response.status_code = 400
            response.json.return_value = {"error_message": "The series does not exist in ALFRED but may exist in FRED"}
        else:
            response.status_code = 200
            response.json.return_value = _payload(
                [_row("2020-01-01", 100, "2020-01-02", params["realtime_end"])],
                params["realtime_end"], realtime_start=params["realtime_start"])
        return response

    session.get.side_effect = get
    rows = MacroDataProvider("key", tmp_path, session=session)._fetch_series(
        "BAMLH0A0HYM2", date(2016, 1, 1), date(2022, 1, 1))
    assert len(rows) == 1
    assert rows[0]["realtime_start"] == "2020-01-02"
    assert len(seen) == 2
    assert all(p["output_type"] == 1 and p["realtime_end"] <= "2022-01-01" for p in seen)


@pytest.mark.parametrize("invalid", [
    {"output_type": 2}, {"realtime_start": "2024-03-28"}, {"realtime_end": "2026-01-01"},
    {"observations": [], "count": 3},
    {"observations": [_row("2024-01-01", "100", "2025-01-01")]},
    {"observations": [_row("2024-01-01", "nan", "2024-02-01")]},
])
def test_provider_rejects_wrong_vintage_or_malformed_data(tmp_path, invalid):
    session = Mock(spec=requests.Session)
    payload = _payload([], "2024-03-28")
    payload.update(invalid)
    session.get.return_value.json.return_value = payload
    provider = MacroDataProvider("key", tmp_path, session=session)
    with pytest.raises(MacroDataUnavailable, match="Invalid ALFRED vintage"):
        provider._fetch_series("TEST", date(2023, 1, 1), date(2024, 3, 28))


def test_network_failure_does_not_expose_key_or_try_current_data(tmp_path):
    session = Mock(spec=requests.Session)
    session.get.side_effect = requests.Timeout("api_key=never-print-me")
    provider = MacroDataProvider("never-print-me", tmp_path, session=session)
    with pytest.raises(MacroDataUnavailable) as caught:
        provider.get_snapshot("2024Q2")
    assert "never-print-me" not in str(caught.value)
    assert caught.value.__suppress_context__
    assert session.get.call_count == 1
    assert not list(tmp_path.rglob("*.json"))


def test_future_quarter_is_not_prematurely_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr("data_provider.macro_data.get_market_now", lambda _market: pd.Timestamp("2024-03-28"))
    session = Mock(spec=requests.Session)
    with pytest.raises(MacroDataUnavailable, match="not yet complete"):
        MacroDataProvider("key", tmp_path, session=session).get_snapshot("2024Q2")
    session.get.assert_not_called()


def test_atomic_freeze_first_writer_wins_and_never_overwrites(tmp_path):
    path = tmp_path / "quarter_decision.json"
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda value: freeze_json(path, {"value": value}), range(30)))
    assert all(result == results[0] for result in results)
    assert freeze_json(path, {"value": "replacement"}) == results[0]
    assert not list(tmp_path.glob("*.tmp"))


def test_unwritable_snapshot_cache_reports_optional_macro_unavailability(tmp_path, monkeypatch):
    def denied(_source, _destination):
        raise PermissionError("read-only cache")

    monkeypatch.setattr("data_provider.macro_data.os.link", denied)
    with pytest.raises(MacroDataUnavailable, match="MATR_DATA_DIR"):
        freeze_json(tmp_path / "quarter.json", {"data": "value"})
    assert not list(tmp_path.iterdir())


def test_corrupt_snapshot_is_not_rebuilt_or_overwritten(tmp_path):
    session = _session(_histories())
    provider = MacroDataProvider("key", tmp_path, session=session)
    provider.get_snapshot("2024Q2")
    path = tmp_path / "v1" / "macro_snapshot_2024Q2.json"
    payload = json.loads(path.read_text())
    payload["features"]["payrolls_3m"] = 999
    damaged = json.dumps(payload)
    path.write_text(damaged)
    session.reset_mock()
    with pytest.raises(MacroSnapshotIntegrityError, match="validation"):
        provider.get_snapshot("2024Q2")
    assert path.read_text() == damaged
    session.get.assert_not_called()


def test_from_config_derives_cache_directory_without_machine_specific_path(tmp_path):
    config = SimpleNamespace(
        fred_api_key=None, matr_data_dir=None, database_path=str(tmp_path / "stock_analysis.db"),
        matr_request_timeout_seconds=3.0, matr_request_retries=1,
    )
    provider = MacroDataProvider.from_config(config)
    assert provider.cache_dir == tmp_path / "matr"
    assert provider.timeout == 3
    assert provider.session.get_adapter("https://").max_retries.total == 1


def test_macro_environment_settings_use_existing_config_loader(tmp_path):
    from src.config import Config

    values = {
        "FRED_API_KEY": "  local-test-key  ", "MATR_DATA_DIR": str(tmp_path / "macro"),
        "MATR_REQUEST_TIMEOUT_SECONDS": "4.5", "MATR_REQUEST_RETRIES": "1",
    }
    with patch("src.config.setup_env"), patch.object(Config, "_parse_litellm_yaml", return_value=[]):
        with patch.dict(os.environ, values, clear=True):
            configured = Config._load_from_env()
        with patch.dict(os.environ, {}, clear=True):
            defaults = Config._load_from_env()
    assert configured.fred_api_key == "local-test-key"
    assert configured.matr_data_dir == str(tmp_path / "macro")
    assert configured.matr_request_timeout_seconds == 4.5
    assert configured.matr_request_retries == 1
    assert defaults.fred_api_key is None
    assert defaults.matr_data_dir is None
    assert defaults.matr_request_timeout_seconds == 15
    assert defaults.matr_request_retries == 2
