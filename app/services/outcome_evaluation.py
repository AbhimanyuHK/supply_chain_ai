"""Deterministic forecast calibration and observed optimization metrics.

Coverage is empirical, not a guarantee of future confidence.
"""
from math import ceil, isfinite


def interval_diagnostics(forecasts: list[dict], outcomes: list[dict]) -> dict:
    predicted = {}
    for point in forecasts:
        key = (point["store_id"], point["product_id"], str(point["date"]))
        predicted[key] = point
    residuals = []
    covered = 0
    total = 0
    absolute_error = 0.0
    for item in outcomes:
        key = (item["store_id"], item["product_id"], str(item["observation_date"]))
        point = predicted.get(key)
        if point is None:
            continue
        actual = float(item["actual_demand_qty"])
        median = float(point["predicted_qty"])
        low = float(point["low_qty"])
        high = float(point["high_qty"])
        if not all(isfinite(v) for v in (actual, median, low, high)):
            continue
        total += 1
        absolute_error += abs(actual - median)
        covered += int(low <= actual <= high)
        residuals.append(max(low - actual, actual - high, 0.0))
    return {
        "matched_observations": total,
        "empirical_interval_coverage": covered / total if total else None,
        "mean_absolute_error": absolute_error / total if total else None,
        "interval_miss_residuals": residuals,
    }


def conformal_margin(residuals: list[float], alpha: float = 0.1) -> float | None:
    """Finite-sample split-conformal quantile on held-out interval misses."""
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between zero and one")
    values = sorted(float(x) for x in residuals if isfinite(float(x)) and x >= 0)
    if not values:
        return None
    rank = ceil((len(values) + 1) * (1 - alpha))
    if rank > len(values):
        return None  # Insufficient calibration data for this confidence level.
    return values[rank - 1]


def outcome_summary(outcomes: list[dict]) -> dict:
    total_demand = sum(float(x["actual_demand_qty"]) for x in outcomes)
    fulfilled = sum(min(float(x["fulfilled_qty"]), float(x["actual_demand_qty"])) for x in outcomes)
    return {
        "observations": len(outcomes),
        "actual_service_level": fulfilled / total_demand if total_demand else None,
        "actual_cost": sum(float(x["actual_cost"]) for x in outcomes),
        "actual_demand": total_demand,
    }
