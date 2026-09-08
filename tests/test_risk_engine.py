# -*- coding: utf-8 -*-
"""Phase 7 tests: RiskEngine sizing and caps."""

import pytest

from src.services.risk_engine import (
    REASON_INVALID_STOP_DISTANCE,
    REASON_OK,
    REASON_PORTFOLIO_CAP,
    REASON_SECTOR_CAP,
    REASON_SINGLE_STOCK_CAP,
    build_execution_plan,
    current_exposure_pct,
)


def test_position_size_calculation():
    # 100k 组合、1% 单笔风险、入场 100、止损 95 -> 风险 1000 / 距离 5 = 200 股。
    plan = build_execution_plan(
        ticker="AAPL", portfolio_value=100_000.0,
        entry_reference=100.0, stop_price=95.0, risk_per_trade=0.01,
    )
    assert plan.approved is True
    assert plan.reason == REASON_OK
    assert plan.suggested_shares == 200
    assert plan.suggested_position_value == pytest.approx(20_000.0)
    assert plan.risk_per_share == pytest.approx(5.0)
    assert plan.portfolio_risk_pct == pytest.approx(1.0)


def test_zero_or_invalid_stop_distance_rejected():
    for stop in (100.0, None, "bad", -5.0):
        plan = build_execution_plan(
            ticker="AAPL", portfolio_value=100_000.0,
            entry_reference=100.0, stop_price=stop,
        )
        assert plan.approved is False
        assert plan.reason == REASON_INVALID_STOP_DISTANCE
        assert plan.suggested_shares == 0


def test_single_stock_limit_enforced():
    # 风险模型要 200 股（2 万），但个股上限 10%（1 万）-> 压缩到 100 股。
    plan = build_execution_plan(
        ticker="AAPL", portfolio_value=100_000.0,
        entry_reference=100.0, stop_price=95.0, max_single_stock_pct=0.10,
    )
    assert plan.approved is True
    assert plan.suggested_shares == 100

    # 已持有 1 万，再买即超限 -> 拒绝。
    plan = build_execution_plan(
        ticker="AAPL", portfolio_value=100_000.0,
        entry_reference=100.0, stop_price=95.0, max_single_stock_pct=0.10,
        current_ticker_position_value=10_000.0,
    )
    assert plan.approved is False
    assert plan.reason == REASON_SINGLE_STOCK_CAP


def test_sector_limit_enforced():
    plan = build_execution_plan(
        ticker="AAPL", portfolio_value=100_000.0,
        entry_reference=100.0, stop_price=95.0, max_single_stock_pct=1.0,
        sector="tech", sector_positions_value=30_000.0, max_sector_pct=0.35,
    )
    assert plan.approved is True
    assert plan.suggested_shares == 50  # 行业再买 5000 即达 3.5 万上限
    assert plan.suggested_position_value == pytest.approx(5_000.0)

    plan = build_execution_plan(
        ticker="AAPL", portfolio_value=100_000.0,
        entry_reference=100.0, stop_price=95.0, max_single_stock_pct=1.0,
        sector="tech", sector_positions_value=35_000.0, max_sector_pct=0.35,
    )
    assert plan.approved is False
    assert plan.reason == REASON_SECTOR_CAP


def test_portfolio_limit_enforced():
    plan = build_execution_plan(
        ticker="AAPL", portfolio_value=100_000.0,
        entry_reference=100.0, stop_price=95.0, max_single_stock_pct=1.0,
        current_positions_value=85_000.0, max_total_exposure_pct=0.90,
    )
    assert plan.approved is True
    assert plan.suggested_shares == 50

    plan = build_execution_plan(
        ticker="AAPL", portfolio_value=100_000.0,
        entry_reference=100.0, stop_price=95.0, max_single_stock_pct=1.0,
        current_positions_value=90_000.0, max_total_exposure_pct=0.90,
    )
    assert plan.approved is False
    assert plan.reason == REASON_PORTFOLIO_CAP


def test_current_exposure_pct():
    assert current_exposure_pct({"AAPL": 20_000.0, "TSLA": 10_000.0}, 100_000.0) == 30.0
    assert current_exposure_pct({}, 100_000.0) == 0.0
