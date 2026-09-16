"""Public opt-in query preserves legacy responses and forwards verified prices."""

from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_auto_tune_api_contract import _report_payload


def test_http_macro_opt_in_and_optional_unavailable_report(monkeypatch):
    from api.v1.endpoints import stocks
    from src.services import indicator_optimizer, macro_router

    bars = [dict(date="2022-01-03", open=100., high=101., low=99., close=100., volume=1000.)]
    service = Mock()
    service.get_history_data.return_value = dict(data=bars, source="offline", price_basis="ADJUSTED_TOTAL_RETURN")
    monkeypatch.setattr(stocks, "StockService", lambda: service)
    monkeypatch.setattr(indicator_optimizer, "run_auto_tune", lambda *args, **kwargs: _report_payload(False))
    # Service/model/execution are exercised together in test_macro_router. This
    # boundary test checks opt-in and optional-failure transport only.
    study = Mock(return_value=macro_router.unavailable_report("FRED_API_KEY required"))
    monkeypatch.setattr(macro_router, "run_macro_router", study)
    app = FastAPI()
    app.include_router(stocks.router, prefix="/stocks")
    client = TestClient(app)

    old = client.get("/stocks/AAPL/auto-tune")
    assert old.status_code == 200
    assert old.json()["macro_router"] is None
    study.assert_not_called()

    response = client.get("/stocks/AAPL/auto-tune", params={"include_macro_router": "true"})
    assert response.status_code == 200
    assert response.json()["macro_router"]["status"] == "UNAVAILABLE"
    assert response.json()["strategies"][0]["key"] == "A"
    forwarded = study.call_args.kwargs
    assert forwarded["symbol"] == "AAPL"
    assert forwarded["price_basis"] == "ADJUSTED_TOTAL_RETURN"
    assert forwarded["benchmark"].symbol == "SPY"
    assert forwarded["benchmark"].values["2022-01-03"] == 100.

    invalid = client.get("/stocks/AAPL/auto-tune", params={"include_macro_router": "nonsense"})
    assert invalid.status_code == 422
