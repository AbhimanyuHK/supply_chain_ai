"""Held-out calibration checks prevent evaluation leakage."""
from app.services.outcome_evaluation import heldout_interval_evaluation


def test_heldout_evaluation_uses_only_prior_observations_for_margin():
    forecasts = [
        {"store_id": 1, "product_id": 1, "date": f"2026-01-{day:02d}",
         "predicted_qty": 10, "low_qty": 8, "high_qty": 12}
        for day in range(1, 13)
    ]
    outcomes = [
        {"store_id": 1, "product_id": 1,
         "observation_date": f"2026-01-{day:02d}",
         "actual_demand_qty": 13 if day <= 10 else 100}
        for day in range(1, 13)
    ]
    report = heldout_interval_evaluation(
        forecasts, outcomes, cutoff_date="2026-01-11", alpha=0.1
    )
    assert report["calibration_count"] == 10
    assert report["evaluation_count"] == 2
    assert report["calibration_margin"] == 1
    assert report["heldout_coverage"] == 0


def test_heldout_evaluation_insufficient_calibration():
    forecasts = [{"store_id": 1, "product_id": 1, "date": "2026-01-01",
                  "predicted_qty": 5, "low_qty": 4, "high_qty": 6}]
    outcomes = [{"store_id": 1, "product_id": 1,
                 "observation_date": "2026-01-01", "actual_demand_qty": 7}]
    report = heldout_interval_evaluation(
        forecasts, outcomes, cutoff_date="2026-01-02", alpha=0.1
    )
    assert report["calibration_margin"] is None
    assert report["heldout_coverage"] is None
