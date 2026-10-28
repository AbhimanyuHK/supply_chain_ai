"""Pure decision-service regression tests."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.schemas.allocation import AllocationLine, AllocationScenario
from app.services.uncertainty_simulation import stress_test
from app.services.replanning_events import SupplyChainEvent, should_replan


def test_stress_test_degrades_service_with_demand_growth():
    scenario = AllocationScenario(
        strategy="baseline",
        lines=[AllocationLine(
            terminal_id=1, store_id=2, product_id=3, quantity=10,
            estimated_transport_cost=5, estimated_delivery_hours=1,
        )],
        total_quantity_allocated=10, total_shortage_quantity=10,
        fulfillment_rate=1.0, total_estimated_cost=5,
        high_priority_shortages_fulfilled=1, high_priority_shortages_total=1,
    )
    shortage = SimpleNamespace(store_id=2, product_id=3, shortage_qty=10)
    result = stress_test(scenario, [shortage], (1.0, 1.2))
    assert result[0].service_level == 1.0
    assert result[1].service_level < 1.0
    assert round(result[1].uncovered_units, 4) == 2


def test_event_cooldown_and_threshold():
    now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
    event = SupplyChainEvent(
        event_id="inventory-1", kind="inventory_changed",
        entity_id="store-2", occurred_at=now, magnitude=0.3,
    )
    assert should_replan(event, last_planned_at=None)
    assert not should_replan(event, last_planned_at=now - timedelta(minutes=5))
    assert should_replan(event, last_planned_at=now - timedelta(minutes=20))
    assert not should_replan(event.model_copy(update={"magnitude": 0.01}), last_planned_at=None)
