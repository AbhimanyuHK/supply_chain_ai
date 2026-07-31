import datetime

import pytest

from app.agents.fleet_assignment_agent import assign_fleet_node
from app.core.business_rules import BusinessRules
from app.models.entities import VehicleStatus
from app.schemas.allocation import AllocationLine, AllocationResult, AllocationScenario
from app.schemas.constraint_validation import ConstraintValidationResult, ScenarioValidation
from app.schemas.fleet import FleetRead
from app.schemas.planning import MasterDataSnapshot
from app.schemas.product import ProductRead
from app.schemas.store import StoreRead
from app.schemas.terminal import TerminalRead

BUSINESS_RULES = BusinessRules()


def _vehicle(vehicle_id, terminal_id, capacity_weight, capacity_volume, status=VehicleStatus.AVAILABLE):
    return FleetRead(
        vehicle_id=vehicle_id, terminal_id=terminal_id, vehicle_type="truck",
        capacity_weight=capacity_weight, capacity_volume=capacity_volume,
        cost_per_km=5.0, fixed_cost=500.0, status=status,
    )


def _product(product_id, weight, volume):
    return ProductRead(
        product_id=product_id, sku=f"SKU-{product_id}", name="P", category="C", weight=weight, volume=volume, cost=10.0
    )


def _snapshot(fleet, products) -> MasterDataSnapshot:
    return MasterDataSnapshot(
        stores=[
            StoreRead(store_id=1, store_name="A", latitude=0, longitude=0, capacity=1000, priority=1),
            StoreRead(store_id=2, store_name="B", latitude=0, longitude=0, capacity=1000, priority=1),
        ],
        terminals=[TerminalRead(terminal_id=1, terminal_name="T", latitude=0, longitude=0, capacity=10000)],
        products=products,
        inventory=[],
        demand_history=[],
        fleet=fleet,
        distance_matrix=[],
        business_rules=BUSINESS_RULES,
        loaded_at=datetime.datetime.now(datetime.timezone.utc),
    )


def _line(store_id, product_id, quantity):
    return AllocationLine(
        terminal_id=1, store_id=store_id, product_id=product_id, quantity=quantity,
        estimated_transport_cost=10.0, estimated_delivery_hours=1.0,
    )


def _scenario(lines) -> AllocationScenario:
    return AllocationScenario(
        strategy="priority_first", lines=lines, total_quantity_allocated=sum(l.quantity for l in lines),
        total_shortage_quantity=0, fulfillment_rate=1.0, total_estimated_cost=100.0,
        high_priority_shortages_fulfilled=1, high_priority_shortages_total=1,
    )


def _state(scenario, snapshot):
    return {
        "allocation": AllocationResult(scenarios=[scenario], recommended_strategy=scenario.strategy),
        "constraint_validation": ConstraintValidationResult(
            scenario_validations=[ScenarioValidation(strategy=scenario.strategy, violations=[], is_valid=True)],
            final_strategy=scenario.strategy, unresolved_violations=[], replanning_triggered=False,
        ),
        "master_data": snapshot,
    }


@pytest.mark.asyncio
async def test_two_small_lines_fit_on_one_vehicle():
    fleet = [_vehicle(1, terminal_id=1, capacity_weight=100, capacity_volume=100)]
    products = [_product(1, weight=2.0, volume=1.0)]
    scenario = _scenario([_line(store_id=1, product_id=1, quantity=10), _line(store_id=2, product_id=1, quantity=10)])
    state = _state(scenario, _snapshot(fleet, products))

    update = await assign_fleet_node(state)

    assignment = update["fleet_assignment"].scenario_assignments[0]
    assert len(assignment.vehicle_loads) == 1
    assert len(assignment.vehicle_loads[0].lines) == 2
    assert assignment.unassigned_lines == []


@pytest.mark.asyncio
async def test_weight_overflow_opens_a_second_vehicle():
    fleet = [
        _vehicle(1, terminal_id=1, capacity_weight=15, capacity_volume=100),
        _vehicle(2, terminal_id=1, capacity_weight=15, capacity_volume=100),
    ]
    products = [_product(1, weight=1.0, volume=0.1)]
    # Each line weighs 10 (fits one vehicle alone), but both together (20) don't
    # fit on one 15-capacity vehicle - forces a second vehicle to open.
    scenario = _scenario([_line(store_id=1, product_id=1, quantity=10), _line(store_id=2, product_id=1, quantity=10)])
    state = _state(scenario, _snapshot(fleet, products))

    update = await assign_fleet_node(state)

    assignment = update["fleet_assignment"].scenario_assignments[0]
    assert len(assignment.vehicle_loads) == 2
    assert assignment.unassigned_lines == []


@pytest.mark.asyncio
async def test_volume_overflow_opens_a_second_vehicle():
    fleet = [
        _vehicle(1, terminal_id=1, capacity_weight=1000, capacity_volume=1.5),
        _vehicle(2, terminal_id=1, capacity_weight=1000, capacity_volume=1.5),
    ]
    products = [_product(1, weight=0.1, volume=0.1)]
    # Each line's volume is 1.0 (fits one vehicle alone), but both together (2.0)
    # don't fit on one 1.5-capacity vehicle - forces a second vehicle to open.
    scenario = _scenario([_line(store_id=1, product_id=1, quantity=10), _line(store_id=2, product_id=1, quantity=10)])
    state = _state(scenario, _snapshot(fleet, products))

    update = await assign_fleet_node(state)

    assignment = update["fleet_assignment"].scenario_assignments[0]
    assert len(assignment.vehicle_loads) == 2


@pytest.mark.asyncio
async def test_line_too_heavy_for_any_vehicle_is_unassignable():
    fleet = [_vehicle(1, terminal_id=1, capacity_weight=5, capacity_volume=100)]
    products = [_product(1, weight=2.0, volume=0.1)]
    scenario = _scenario([_line(store_id=1, product_id=1, quantity=10)])  # weighs 20, no vehicle fits
    state = _state(scenario, _snapshot(fleet, products))

    update = await assign_fleet_node(state)

    assignment = update["fleet_assignment"].scenario_assignments[0]
    assert assignment.vehicle_loads == []
    assert len(assignment.unassigned_lines) == 1
    assert assignment.unassigned_lines[0].unassignable is True
    assert assignment.unassigned_lines[0].vehicle_id is None


@pytest.mark.asyncio
async def test_unavailable_vehicles_are_ignored():
    fleet = [_vehicle(1, terminal_id=1, capacity_weight=100, capacity_volume=100, status=VehicleStatus.MAINTENANCE)]
    products = [_product(1, weight=1.0, volume=1.0)]
    scenario = _scenario([_line(store_id=1, product_id=1, quantity=5)])
    state = _state(scenario, _snapshot(fleet, products))

    update = await assign_fleet_node(state)

    assignment = update["fleet_assignment"].scenario_assignments[0]
    assert assignment.vehicle_loads == []
    assert len(assignment.unassigned_lines) == 1


@pytest.mark.asyncio
async def test_no_scenarios_short_circuits():
    state = {
        "allocation": AllocationResult(scenarios=[], recommended_strategy=None),
        "constraint_validation": ConstraintValidationResult(
            scenario_validations=[], final_strategy=None, unresolved_violations=[], replanning_triggered=False
        ),
        "master_data": _snapshot([], []),
    }

    update = await assign_fleet_node(state)

    assert update["fleet_assignment"].scenario_assignments == []
    assert update["fleet_assignment"].fell_back is False
