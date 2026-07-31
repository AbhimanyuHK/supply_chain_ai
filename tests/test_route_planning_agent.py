import datetime

import pytest

from app.agents.route_planning_agent import plan_route_node
from app.core.business_rules import BusinessRules
from app.models.entities import VehicleStatus
from app.schemas.distance import DistanceMatrixRead
from app.schemas.fleet import FleetRead
from app.schemas.fleet_assignment import (
    AssignedLine,
    FleetAssignmentResult,
    ScenarioFleetAssignment,
    VehicleLoad,
)
from app.schemas.planning import MasterDataSnapshot
from app.schemas.product import ProductRead
from app.schemas.store import StoreRead
from app.schemas.terminal import TerminalRead

BUSINESS_RULES = BusinessRules()


def _distance(terminal_id, store_id, distance_km, travel_time):
    return DistanceMatrixRead(terminal_id=terminal_id, store_id=store_id, distance_km=distance_km, travel_time=travel_time)


def _snapshot(distance_rows) -> MasterDataSnapshot:
    return MasterDataSnapshot(
        stores=[
            StoreRead(store_id=1, store_name="Far", latitude=0, longitude=0, capacity=1000, priority=1),
            StoreRead(store_id=2, store_name="Near", latitude=0, longitude=0, capacity=1000, priority=1),
        ],
        terminals=[TerminalRead(terminal_id=1, terminal_name="T", latitude=0, longitude=0, capacity=10000)],
        products=[ProductRead(product_id=1, sku="SKU-1", name="P", category="C", weight=1.0, volume=1.0, cost=10.0)],
        inventory=[],
        demand_history=[],
        fleet=[
            FleetRead(
                vehicle_id=1, terminal_id=1, vehicle_type="truck", capacity_weight=1000, capacity_volume=100,
                cost_per_km=5.0, fixed_cost=500.0, status=VehicleStatus.AVAILABLE,
            )
        ],
        distance_matrix=distance_rows,
        business_rules=BUSINESS_RULES,
        loaded_at=datetime.datetime.now(datetime.timezone.utc),
    )


def _line(store_id):
    return AssignedLine(terminal_id=1, store_id=store_id, product_id=1, quantity=5, vehicle_id=1, unassignable=False)


@pytest.mark.asyncio
async def test_stops_ordered_nearest_first():
    # Store 1 is far (50km), store 2 is near (10km) - route must visit 2 first.
    snapshot = _snapshot([_distance(1, 1, 50.0, 1.25), _distance(1, 2, 10.0, 0.25)])
    load = VehicleLoad(
        vehicle_id=1, terminal_id=1, lines=[_line(1), _line(2)],
        total_weight=10, total_volume=10, capacity_weight=1000, capacity_volume=100,
    )
    state = {
        "fleet_assignment": FleetAssignmentResult(
            scenario_assignments=[ScenarioFleetAssignment(strategy="priority_first", vehicle_loads=[load], unassigned_lines=[])],
            fell_back=False,
        ),
        "master_data": snapshot,
    }

    update = await plan_route_node(state)

    route = update["route_planning"].scenario_routes[0].vehicle_routes[0]
    assert [stop.store_id for stop in route.stops] == [2, 1]
    assert route.total_route_distance_km == 60.0


@pytest.mark.asyncio
async def test_multiple_lines_to_same_store_dedup_to_one_stop():
    snapshot = _snapshot([_distance(1, 1, 20.0, 0.5)])
    load = VehicleLoad(
        vehicle_id=1, terminal_id=1, lines=[_line(1), _line(1)],
        total_weight=10, total_volume=10, capacity_weight=1000, capacity_volume=100,
    )
    state = {
        "fleet_assignment": FleetAssignmentResult(
            scenario_assignments=[ScenarioFleetAssignment(strategy="priority_first", vehicle_loads=[load], unassigned_lines=[])],
            fell_back=False,
        ),
        "master_data": snapshot,
    }

    update = await plan_route_node(state)

    route = update["route_planning"].scenario_routes[0].vehicle_routes[0]
    assert len(route.stops) == 1
    assert route.total_route_distance_km == 20.0


@pytest.mark.asyncio
async def test_route_cost_counts_fixed_cost_once_not_per_line():
    snapshot = _snapshot([_distance(1, 1, 10.0, 0.25), _distance(1, 2, 20.0, 0.5)])
    load = VehicleLoad(
        vehicle_id=1, terminal_id=1, lines=[_line(1), _line(2)],
        total_weight=10, total_volume=10, capacity_weight=1000, capacity_volume=100,
    )
    state = {
        "fleet_assignment": FleetAssignmentResult(
            scenario_assignments=[ScenarioFleetAssignment(strategy="priority_first", vehicle_loads=[load], unassigned_lines=[])],
            fell_back=False,
        ),
        "master_data": snapshot,
    }

    update = await plan_route_node(state)

    route = update["route_planning"].scenario_routes[0].vehicle_routes[0]
    # fixed_cost (500) once + cost_per_km (5) * total_distance (30) = 650, NOT
    # 500 charged per line as Cost Optimization's per-line proxy would.
    assert route.route_transportation_cost == 650.0


@pytest.mark.asyncio
async def test_no_fleet_assignments_short_circuits():
    state = {
        "fleet_assignment": FleetAssignmentResult(scenario_assignments=[], fell_back=False),
        "master_data": _snapshot([]),
    }

    update = await plan_route_node(state)

    assert update["route_planning"].scenario_routes == []
