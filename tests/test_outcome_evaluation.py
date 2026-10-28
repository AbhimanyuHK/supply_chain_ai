"""Deterministic observed outcome and calibration tests."""
import pytest

from app.services.outcome_evaluation import (
    conformal_margin, interval_diagnostics, outcome_summary,
)


def test_forecast_diagnostics_matches_by_pair_and_date():
    forecasts = [
        {"store_id": 1, "product_id": 2, "date": "2026-10-01",
         "predicted_qty": 10, "low_qty": 8, "high_qty": 12},
    ]
    outcomes = [
        {"store_id": 1, "product_id": 2, "observation_date": "2026-10-01",
         "actual_demand_qty": 15, "fulfilled_qty": 10, "actual_cost": 100},
        {"store_id": 2, "product_id": 2, "observation_date": "2026-10-01",
         "actual_demand_qty": 99, "fulfilled_qty": 0, "actual_cost": 0},
    ]
    report = interval_diagnostics(forecasts, outcomes)
    assert report["matched_observations"] == 1
    assert report["empirical_interval_coverage"] == 0
    assert report["mean_absolute_error"] == 5
    assert report["interval_miss_residuals"] == [3]


def test_conformal_margin_requires_enough_data():
    assert conformal_margin([], 0.1) is None
    assert conformal_margin([0, 1, 2, 3, 4, 5, 6, 7, 8, 9], 0.1) == 9
    assert conformal_margin([0, 1], 0.1) is None
    with pytest.raises(ValueError):
        conformal_margin([1], 1.0)


def test_observed_service_level_is_bounded():
    report = outcome_summary([
        {"actual_demand_qty": 10, "fulfilled_qty": 12, "actual_cost": 20},
        {"actual_demand_qty": 10, "fulfilled_qty": 5, "actual_cost": 30},
    ])
    assert report["actual_service_level"] == 0.75
    assert report["actual_cost"] == 50


def test_no_observations_is_explicitly_unavailable():
    assert outcome_summary([])["actual_service_level"] is None
    assert interval_diagnostics([], [])["empirical_interval_coverage"] is None
