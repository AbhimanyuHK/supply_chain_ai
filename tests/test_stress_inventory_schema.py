"""Regression test for real inventory-analysis shortage schema."""
from types import SimpleNamespace

from app.schemas.allocation import AllocationLine, AllocationScenario
from app.services.uncertainty_simulation import stress_test


def test_stress_test_accepts_inventory_analysis_record():
    scenario = AllocationScenario(
        strategy="test",
        lines=[AllocationLine(
            terminal_id=1, store_id=2, product_id=3, quantity=10,
            estimated_transport_cost=1.0, estimated_delivery_hours=1.0,
        )],
        total_quantity_allocated=10,
        total_shortage_quantity=10,
        fulfillment_rate=1.0,
        total_estimated_cost=1.0,
        high_priority_shortages_fulfilled=1,
        high_priority_shortages_total=1,
    )
    shortage = SimpleNamespace(location_id=2, product_id=3, shortage_qty=10)
    metrics = stress_test(scenario, [shortage], multipliers=(1.0, 1.5))
    assert metrics[0].service_level == 1.0
    assert metrics[1].uncovered_units == 5.0
