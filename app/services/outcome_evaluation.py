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


def heldout_interval_evaluation(
    forecasts: list[dict], outcomes: list[dict], *,
    cutoff_date: str, alpha: float = 0.1,
) -> dict:
    """Calibrate on observations before cutoff, evaluate strictly after cutoff.

    Caller must ensure forecasts were generated before each outcome; otherwise
    this is only retrospective validation, not prospective model validation.
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between zero and one")
    calibration = [row for row in outcomes if str(row["observation_date"]) < cutoff_date]
    evaluation = [row for row in outcomes if str(row["observation_date"]) >= cutoff_date]
    fitted = interval_diagnostics(forecasts, calibration)
    margin = conformal_margin(fitted["interval_miss_residuals"], alpha)
    if margin is None:
        return {
            "calibration_count": fitted["matched_observations"],
            "evaluation_count": 0,
            "calibration_margin": None,
            "heldout_coverage": None,
            "reason": "Insufficient calibration observations",
        }
    widened = [
        {**point, "low_qty": max(0, float(point["low_qty"]) - margin),
         "high_qty": float(point["high_qty"]) + margin}
        for point in forecasts
    ]
    assessed = interval_diagnostics(widened, evaluation)
    return {
        "calibration_count": fitted["matched_observations"],
        "evaluation_count": assessed["matched_observations"],
        "calibration_margin": margin,
        "heldout_coverage": assessed["empirical_interval_coverage"],
        "heldout_mae": assessed["mean_absolute_error"],
        "reason": None if assessed["matched_observations"] else "No matched held-out outcomes",
    }
