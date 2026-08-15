"""Historical trigger threshold tuning and transaction benefit simulation."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from src.services.indicator_service import DEFAULT_THRESHOLDS, compute_indicators

TRIGGER_THRESHOLD_KEYS = {
    "macd": ("macd_buy", "macd_sell"),
    "kdj": ("kdj_buy", "kdj_sell"),
    "rsi": ("rsi_buy", "rsi_sell"),
    "obv": ("bol_constant", "bol_constant"),
}

TRIGGER_LABELS = {
    "macd": "MACD",
    "kdj": "KDJ",
    "rsi": "RSI",
    "obv": "OBV",
}


def simulate_transactions(
    dates: Sequence[str],
    close: Sequence[float],
    triggers: Dict[str, Sequence[float | None]],
    window_days: int,
) -> Dict[str, Any]:
    """Simulate non-overlapping windows with at most one buy and sell each."""
    n = len(close)
    benefit_series: List[float | None] = [None] * n
    transactions: List[Dict[str, Any]] = []
    accumulated = 1.0
    for start in range(0, n, window_days):
        end = min(start + window_days, n)
        buy_index = next((i for i in range(start, end) if triggers["buy"][i] is not None), None)
        if buy_index is None:
            continue
        sell_index = next((i for i in range(buy_index + 1, end) if triggers["sell"][i] is not None), None)
        if sell_index is None or close[buy_index] <= 0:
            continue
        buy_price = float(triggers["buy"][buy_index] or close[buy_index])
        sell_price = float(triggers["sell"][sell_index] or close[sell_index])
        benefit = (sell_price / buy_price - 1.0) * 100.0
        accumulated *= 1.0 + benefit / 100.0
        for index in range(sell_index, end):
            benefit_series[index] = (accumulated - 1.0) * 100.0
        transactions.append({
            "buy_date": dates[buy_index], "sell_date": dates[sell_index],
            "buy_price": buy_price, "sell_price": sell_price, "benefit_pct": benefit,
        })
    return {
        "benefit_series": benefit_series,
        "accumulated_benefit_pct": (accumulated - 1.0) * 100.0,
        "transactions": transactions,
    }


def _candidates(key: str) -> List[float]:
    if key == "bol_constant":
        return [round(v, 2) for v in [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5]]
    if key in ("macd_buy", "macd_sell"):
        return [round(v, 2) for v in [0.5, 0.6, 0.7, 0.8, 0.9, 0.99]]
    return [float(v) for v in range(5, 101, 5)]


def optimize_indicator_thresholds(
    bars: Sequence[Dict[str, Any]], trigger: str, window_days: int,
) -> Dict[str, Any]:
    """Grid-search the selected trigger's buy/sell thresholds."""
    if trigger not in TRIGGER_THRESHOLD_KEYS:
        raise ValueError("unsupported trigger")
    buy_key, sell_key = TRIGGER_THRESHOLD_KEYS[trigger]
    best: Dict[str, Any] | None = None
    for buy_value in _candidates(buy_key):
        sell_values = [buy_value] if buy_key == sell_key else _candidates(sell_key)
        for sell_value in sell_values:
            thresholds = dict(DEFAULT_THRESHOLDS)
            thresholds[buy_key] = buy_value
            thresholds[sell_key] = sell_value
            computed = compute_indicators(bars, thresholds)
            raw = computed["triggers"]
            simulation = simulate_transactions(
                computed["dates"], computed["close"],
                {"buy": raw[f"{trigger}_buy"], "sell": raw[f"{trigger}_sell"]}, window_days,
            )
            score = simulation["accumulated_benefit_pct"]
            candidate = {"score": score, "transactions": len(simulation["transactions"]), "thresholds": thresholds, "simulation": simulation}
            if best is None or (score, -candidate["transactions"]) > (best["score"], -best["transactions"]):
                best = candidate
    assert best is not None
    return {
        "trigger": trigger, "window_days": window_days,
        "thresholds": best["thresholds"],
        "accumulated_benefit_pct": best["score"],
        "transactions": best["simulation"]["transactions"],
        "benefit_series": best["simulation"]["benefit_series"],
    }


def calculate_trigger_benefits(
    computed: Dict[str, Any], window_days: int,
) -> Dict[str, Dict[str, Any]]:
    """Calculate an aligned cumulative benefit curve for every trigger group."""
    output: Dict[str, Dict[str, Any]] = {}
    for trigger, label in TRIGGER_LABELS.items():
        raw = computed["triggers"]
        output[trigger] = simulate_transactions(
            computed["dates"],
            computed["close"],
            {"buy": raw[f"{trigger}_buy"], "sell": raw[f"{trigger}_sell"]},
            window_days,
        )
        output[trigger]["label"] = label
    return output