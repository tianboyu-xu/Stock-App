"""Exercise request validation before any market-data service call."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.endpoints import stocks


@pytest.mark.parametrize("config", ['[]', '{"version":2}', '{"risk":{"maximum_exposure":2}}', '{"allocation":{"q":{"minimum_visit_count":0}}}'])
def test_invalid_aces_request_fails_before_data_fetch(monkeypatch, config):
    monkeypatch.setattr(stocks, "StockService", lambda: pytest.fail("invalid ACES request fetched data"))
    app = FastAPI()
    app.add_api_route('/stocks/{stock_code}/auto-tune', stocks.auto_tune_stock)
    response = TestClient(app).get('/stocks/MSFT/auto-tune', params={'aces_config': config})
    assert response.status_code == 422
    assert response.json()['detail']['error'] == 'invalid_aces_config'


@pytest.mark.parametrize("config", ['[]', '{"q":{"episodes":0}}', '{"policy_mode":"DQN"}', '{invalid',
                                    '{"lambda_opportunity":-1}', '{"opportunity_band":0}',
                                    '{"validation_folds":1}', '{"threshold_iterations":99}',
                                    '{"economic":{"target_cagr":-1}}', '{"economic":{"alpha_reward_cap":2}}',
                                    '{"economic":{"minimum_cagr_days":0}}',
                                    '{"economic":{"benchmark_missing_policy":"SILENT"}}'])
def test_invalid_allocation_request_fails_before_data_fetch(monkeypatch, config):
    def unexpected_service():
        pytest.fail("invalid request reached market-data service")
    monkeypatch.setattr(stocks, "StockService", unexpected_service)
    app = FastAPI()
    app.add_api_route('/stocks/{stock_code}/auto-tune', stocks.auto_tune_stock)
    response = TestClient(app).get('/stocks/AAPL/auto-tune', params={'allocation_config': config})
    assert response.status_code == 422
    assert response.json()['detail']['error'] == 'invalid_allocation_config'


def test_route_passes_only_verified_adjusted_same_session_benchmark(monkeypatch):
    from src.services import indicator_optimizer
    from src.services.allocation.economic_reward import BenchmarkDataMissing
    calls = []
    class Service:
        def get_history_data(self, stock_code, **kwargs):
            calls.append(stock_code)
            return dict(price_basis="ADJUSTED_TOTAL_RETURN", data=[dict(date="2020-01-02", close=100)])
    def run(*args, allocation_benchmark=None, **kwargs):
        assert allocation_benchmark.symbol == "SPY"
        assert allocation_benchmark.values["2020-01-02"] == 100
        raise BenchmarkDataMissing("BENCHMARK_DATA_MISSING: fixture has incomplete dates")
    monkeypatch.setattr(stocks, "StockService", Service)
    monkeypatch.setattr(indicator_optimizer, "run_auto_tune", run)
    app = FastAPI()
    app.add_api_route('/stocks/{stock_code}/auto-tune', stocks.auto_tune_stock)
    response = TestClient(app).get('/stocks/AAPL/auto-tune')
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "BENCHMARK_DATA_MISSING"
    assert "SPY" in calls


@pytest.mark.parametrize("code,basis", [("600519", "ADJUSTED_TOTAL_RETURN"), ("AAPL", "UNVERIFIED")])
def test_route_does_not_use_mismatched_market_or_unknown_price_basis(monkeypatch, code, basis):
    from src.services import indicator_optimizer
    from src.services.allocation.economic_reward import BenchmarkDataMissing
    class Service:
        def get_history_data(self, **kwargs):
            return dict(price_basis=basis, data=[])
    def run(*args, allocation_benchmark=None, **kwargs):
        assert allocation_benchmark is None
        raise BenchmarkDataMissing("BENCHMARK_DATA_MISSING")
    monkeypatch.setattr(stocks, "StockService", Service)
    monkeypatch.setattr(indicator_optimizer, "run_auto_tune", run)
    app = FastAPI()
    app.add_api_route('/stocks/{stock_code}/auto-tune', stocks.auto_tune_stock)
    response = TestClient(app).get(f'/stocks/{code}/auto-tune')
    assert response.json()["detail"]["error"] == "BENCHMARK_DATA_MISSING"
