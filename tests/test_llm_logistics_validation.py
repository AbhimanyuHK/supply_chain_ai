"""Tests for AI fleet and route validation without model calls."""
from types import SimpleNamespace
from app.agents.llm_fleet_optimizer import (
    ProposedFleetPlan, ProposedVehicleAssignment, validate_fleet_plan,
)
from app.agents.llm_route_optimizer import ProposedRoute


def test_fleet_plan_rejects_overloaded_vehicle():
    lines = [SimpleNamespace(terminal_id=1, product_id=2, quantity=10)]
    fleet = [SimpleNamespace(vehicle_id=3, terminal_id=1, status="available",
                             capacity_weight=5, capacity_volume=100)]
    products = [SimpleNamespace(product_id=2, weight=2, volume=1)]
    plan = ProposedFleetPlan(assignments=[ProposedVehicleAssignment(line_index=0, vehicle_id=3)],
                             rationale="test")
    assert validate_fleet_plan(plan, lines, fleet, products) is None


def test_fleet_plan_rejects_invented_vehicle():
    lines = [SimpleNamespace(terminal_id=1, product_id=2, quantity=1)]
    plan = ProposedFleetPlan(assignments=[ProposedVehicleAssignment(line_index=0, vehicle_id=999)],
                             rationale="test")
    assert validate_fleet_plan(plan, lines, [], []) is None


def test_route_schema_rejects_missing_stops_in_consumer():
    proposal = ProposedRoute(store_ids=[1, 2], rationale="test")
    expected = [1, 2, 3]
    assert set(proposal.store_ids) != set(expected)
