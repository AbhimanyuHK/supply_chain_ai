from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pytest
from app.schemas.allocation import AllocationLine, AllocationScenario
from app.services.uncertainty_simulation import stress_test
from app.services.approval_workflow import ApprovalDecision, ApprovalStatus, decide
from app.services.replanning_events import SupplyChainEvent, should_replan


def test_stress_test_sensitivity():
    scenario = AllocationScenario(
        strategy="sample", lines=[AllocationLine(
            terminal_id=1, store_id=2, product_id=3, quantity=10,
            estimated_transport_cost=1, estimated_delivery_hours=1)],
        total_quantity_allocated=10, total_shortage_quantity=10,
        fulfillment_rate=1, total_estimated_cost=1,
        high_priority_shortages_fulfilled=1, high_priority_shortages_total=1)
    results = stress_test(scenario, [SimpleNamespace(store_id=2, product_id=3, shortage_qty=10)])
    assert results[1].service_level == 1
    assert results[2].service_level < 1


def test_approval_is_single_transition():
    initial = ApprovalDecision(run_id=1, strategy="sample")
    approved = decide(initial, reviewer="planner", approve=True, reason="Reviewed")
    assert approved.status == ApprovalStatus.APPROVED
    with pytest.raises(ValueError):
        decide(approved, reviewer="planner", approve=False, reason="changed")


def test_event_replanning_cooldown():
    now = datetime.now(timezone.utc)
    event = SupplyChainEvent(event_id="e1", kind="demand_spike", entity_id="store-2",
                             occurred_at=now, magnitude=0.2)
    assert not should_replan(event, last_planned_at=now - timedelta(minutes=5))
    assert should_replan(event, last_planned_at=now - timedelta(minutes=20))
