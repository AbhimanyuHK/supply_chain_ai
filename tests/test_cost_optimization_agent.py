import datetime

import pytest

from app.agents.cost_optimization_agent import _pick_vehicle, _recommend, optimize_cost_node
from app.core.business_rules import BusinessRules
from app.models.entities import VehicleStatus
from app.schemas.allocation import AllocationLine, AllocationResult, AllocationScenario
from app.schemas.cost_optimization import CostOptimizationResult, ScenarioCostSummary
from app.schemas.distance import DistanceMatrixRead
from app.schemas.fleet import FleetRead
from app.schemas.planning import MasterDataSnapshot, PlanningRequest
from app.schemas.product import ProductRead
from app.schemas.store import StoreRead
from app.schemas.terminal import TerminalRead

BUSINESS_RULES = BusinessRules(
    default_lead_time_days=2,
    estimated_transport_cost_per_km=50.0,
    warehouse_handling_cost_per_unit=5.0,
    inventory_holding_cost_rate=0.0005,
    default_safety_stock_days=7,
    delay_penalty_per_hour=20.0,
)


def _vehicle(vehicle_id, terminal_id, capacity_weight, capacity_volume, cost_per_km, fixed_cost, status=VehicleStatus.AVAILABLE):
    return FleetRead(
        vehicle_id=vehicle_id,
        terminal_id=terminal_id,
        vehicle_type="truck",
        capacity_weight=capacity_weight,
        capacity_volume=capacity_volume,
        cost_per_km=cost_per_km,
        fixed_cost=fixed_cost,
        status=status,
    )


def test_pick_vehicle_chooses_cheapest_capable_vehicle():
    fleet = [
        _vehicle(1, terminal_id=1, capacity_weight=100, capacity_volume=10, cost_per_km=5, fixed_cost=500),
        _vehicle(2, terminal_id=1, capacity_weight=100, capacity_volume=10, cost_per_km=2, fixed_cost=100),
        _vehicle(3, terminal_id=2, capacity_weight=1000, capacity_volume=100, cost_per_km=1, fixed_cost=50),
    ]

    vehicle, capable = _pick_vehicle(fleet, terminal_id=1, shipment_weight=50, shipment_volume=5)

    assert capable is True
    assert vehicle.vehicle_id == 2  # cheaper fixed_cost among the two capable options at terminal 1


def test_pick_vehicle_falls_back_to_largest_when_none_capable():
    fleet = [
        _vehicle(1, terminal_id=1, capacity_weight=10, capacity_volume=1, cost_per_km=5, fixed_cost=500),
        _vehicle(2, terminal_id=1, capacity_weight=20, capacity_volume=2, cost_per_km=5, fixed_cost=500),
    ]

    vehicle, capable = _pick_vehicle(fleet, terminal_id=1, shipment_weight=100, shipment_volume=10)

    assert capable is False
    assert vehicle.vehicle_id == 2  # largest capacity, even though insufficient


def test_pick_vehicle_ignores_unavailable_vehicles():
    fleet = [
        _vehicle(1, terminal_id=1, capacity_weight=1000, capacity_volume=100, cost_per_km=1, fixed_cost=10, status=VehicleStatus.MAINTENANCE),
    ]

    vehicle, capable = _pick_vehicle(fleet, terminal_id=1, shipment_weight=10, shipment_volume=1)

    assert vehicle is None
    assert capable is False


def test_pick_vehicle_returns_none_when_no_fleet_at_terminal():
    vehicle, capable = _pick_vehicle([], terminal_id=1, shipment_weight=10, shipment_volume=1)
    assert vehicle is None
    assert capable is False


def _snapshot(fleet, distance_rows) -> MasterDataSnapshot:
    return MasterDataSnapshot(
        stores=[StoreRead(store_id=1, store_name="S", latitude=0, longitude=0, capacity=100, priority=1)],
        terminals=[TerminalRead(terminal_id=1, terminal_name="T", latitude=0, longitude=0, capacity=1000)],
        products=[
            ProductRead(product_id=1, sku="SKU-1", name="P", category="C", weight=2.0, volume=0.5, cost=100.0)
        ],
        inventory=[],
        demand_history=[],
        fleet=fleet,
        distance_matrix=distance_rows,
        business_rules=BUSINESS_RULES,
        loaded_at=datetime.datetime.now(datetime.timezone.utc),
    )


def _scenario(strategy: str, quantity: int, high_priority_fulfilled=1, high_priority_total=1) -> AllocationScenario:
    line = AllocationLine(
        terminal_id=1, store_id=1, product_id=1, quantity=quantity,
        estimated_transport_cost=999.0,  # deliberately wrong - Cost Optimization must recompute, not trust this.
        estimated_delivery_hours=1.0,
    )
    return AllocationScenario(
        strategy=strategy,
        lines=[line],
        total_quantity_allocated=quantity,
        total_shortage_quantity=quantity,
        fulfillment_rate=1.0,
        total_estimated_cost=999.0,
        high_priority_shortages_fulfilled=high_priority_fulfilled,
        high_priority_shortages_total=high_priority_total,
        rank=1,
        rationale="test",
    )


@pytest.mark.asyncio
async def test_optimize_cost_node_recomputes_real_cost_ignoring_allocation_estimate():
    fleet = [_vehicle(1, terminal_id=1, capacity_weight=1000, capacity_volume=100, cost_per_km=2.0, fixed_cost=100.0)]
    distance_rows = [DistanceMatrixRead(terminal_id=1, store_id=1, distance_km=10.0, travel_time=1.0)]
    snapshot = _snapshot(fleet, distance_rows)
    scenario = _scenario("priority_first", quantity=10)

    state = {
        "request": PlanningRequest(),
        "master_data": snapshot,
        "allocation": AllocationResult(scenarios=[scenario], recommended_strategy="priority_first"),
    }

    update = await optimize_cost_node(state)
    result: CostOptimizationResult = update["cost_optimization"]

    assert len(result.scenarios) == 1
    costed = result.scenarios[0]
    line = costed.lines[0]

    # transportation = fixed_cost(100) + cost_per_km(2) * distance(10) = 120, NOT the
    # allocation scenario's bogus estimated_transport_cost of 999.
    assert line.transportation_cost == 120.0
    assert line.vehicle_id == 1
    assert line.vehicle_capacity_exceeded is False

    # handling = 5.0/unit * 10 units = 50
    assert line.handling_cost == 50.0
    # holding = 10 * cost(100) * rate(0.0005) * 7 days = 3.5
    assert line.holding_cost == pytest.approx(3.5)
    # travel_time (1h) < acceptable (2 days * 24h) -> no delay penalty
    assert line.delay_penalty == 0.0

    assert costed.total_cost == pytest.approx(120.0 + 50.0 + 3.5 + 0.0)
    assert costed.fully_satisfies_high_priority is True
    assert result.recommended_strategy == "priority_first"


@pytest.mark.asyncio
async def test_optimize_cost_node_applies_delay_penalty_for_slow_delivery():
    fleet = [_vehicle(1, terminal_id=1, capacity_weight=1000, capacity_volume=100, cost_per_km=1.0, fixed_cost=10.0)]
    # 100 hours of travel time, way beyond the 2-day (48h) acceptable lead time.
    distance_rows = [DistanceMatrixRead(terminal_id=1, store_id=1, distance_km=1.0, travel_time=100.0)]
    snapshot = _snapshot(fleet, distance_rows)
    scenario = _scenario("priority_first", quantity=1)

    state = {
        "request": PlanningRequest(),
        "master_data": snapshot,
        "allocation": AllocationResult(scenarios=[scenario], recommended_strategy="priority_first"),
    }

    update = await optimize_cost_node(state)
    line = update["cost_optimization"].scenarios[0].lines[0]

    # delay_hours = 100 - 48 = 52; penalty = 52 * 20.0/hour = 1040
    assert line.delay_penalty == pytest.approx(1040.0)


@pytest.mark.asyncio
async def test_optimize_cost_node_flags_capacity_exceeded_and_falls_back_to_proxy_rate():
    # Only a tiny vehicle available - can't carry the shipment.
    fleet = [_vehicle(1, terminal_id=1, capacity_weight=1, capacity_volume=1, cost_per_km=1.0, fixed_cost=10.0)]
    distance_rows = [DistanceMatrixRead(terminal_id=1, store_id=1, distance_km=10.0, travel_time=1.0)]
    snapshot = _snapshot(fleet, distance_rows)
    scenario = _scenario("priority_first", quantity=1000)  # weight = 1000*2.0 = 2000, way over capacity

    state = {
        "request": PlanningRequest(),
        "master_data": snapshot,
        "allocation": AllocationResult(scenarios=[scenario], recommended_strategy="priority_first"),
    }

    update = await optimize_cost_node(state)
    line = update["cost_optimization"].scenarios[0].lines[0]

    assert line.vehicle_capacity_exceeded is True
    # Still gets a real vehicle assigned (best-effort largest available)
    assert line.vehicle_id == 1


@pytest.mark.asyncio
async def test_optimize_cost_node_recommends_lowest_cost_among_fully_satisfying_scenarios():
    fleet = [_vehicle(1, terminal_id=1, capacity_weight=1000, capacity_volume=100, cost_per_km=1.0, fixed_cost=10.0)]
    distance_rows = [DistanceMatrixRead(terminal_id=1, store_id=1, distance_km=1.0, travel_time=1.0)]
    snapshot = _snapshot(fleet, distance_rows)

    cheap_but_incomplete = _scenario("score_first", quantity=1, high_priority_fulfilled=0, high_priority_total=1)
    expensive_but_complete = _scenario("priority_first", quantity=50, high_priority_fulfilled=1, high_priority_total=1)

    state = {
        "request": PlanningRequest(),
        "master_data": snapshot,
        "allocation": AllocationResult(
            scenarios=[cheap_but_incomplete, expensive_but_complete], recommended_strategy="score_first"
        ),
    }

    update = await optimize_cost_node(state)
    result: CostOptimizationResult = update["cost_optimization"]

    # Even though score_first is cheaper, it doesn't fully satisfy high-priority shortages,
    # so priority_first (the only fully-satisfying option) must be recommended instead.
    assert result.recommended_strategy == "priority_first"
    assert "fully satisfy" in result.recommendation_rationale


@pytest.mark.asyncio
async def test_optimize_cost_node_skips_when_no_allocation_scenarios():
    state = {"master_data": None, "allocation": AllocationResult(scenarios=[], recommended_strategy=None)}

    update = await optimize_cost_node(state)
    result: CostOptimizationResult = update["cost_optimization"]

    assert result.scenarios == []
    assert result.recommended_strategy is None
    assert "No allocation scenarios" in update["trace"][0]


def _bare_cost_summary(strategy: str, total_cost: float, fulfillment_rate: float) -> ScenarioCostSummary:
    """A ScenarioCostSummary with no lines - just for exercising `_recommend`'s
    selection logic directly, independent of the full cost-computation pipeline."""
    return ScenarioCostSummary(
        strategy=strategy,
        lines=[],
        total_transportation_cost=total_cost,
        total_handling_cost=0.0,
        total_holding_cost=0.0,
        total_delay_penalty=0.0,
        total_cost=total_cost,
        high_priority_shortages_fulfilled=1,
        high_priority_shortages_total=1,
        fully_satisfies_high_priority=True,
        fulfillment_rate=fulfillment_rate,
    )


def test_recommend_minimize_cost_picks_cheapest_when_both_fully_satisfy_high_priority():
    cheap_lower_fulfillment = _bare_cost_summary("cheap", total_cost=100.0, fulfillment_rate=0.7)
    expensive_higher_fulfillment = _bare_cost_summary("expensive", total_cost=500.0, fulfillment_rate=1.0)

    strategy, rationale = _recommend(
        [cheap_lower_fulfillment, expensive_higher_fulfillment], objective="minimize_cost"
    )

    assert strategy == "cheap"
    assert "lowest total cost" in rationale


def test_recommend_maximize_service_level_picks_highest_fulfillment_regardless_of_cost():
    cheap_lower_fulfillment = _bare_cost_summary("cheap", total_cost=100.0, fulfillment_rate=0.7)
    expensive_higher_fulfillment = _bare_cost_summary("expensive", total_cost=500.0, fulfillment_rate=1.0)

    strategy, rationale = _recommend(
        [cheap_lower_fulfillment, expensive_higher_fulfillment], objective="maximize_service_level"
    )

    assert strategy == "expensive"
    assert "fulfillment" in rationale.lower()


def test_recommend_maximize_service_level_uses_cost_as_tiebreaker():
    tied_fulfillment_cheap = _bare_cost_summary("cheap", total_cost=100.0, fulfillment_rate=0.9)
    tied_fulfillment_expensive = _bare_cost_summary("expensive", total_cost=500.0, fulfillment_rate=0.9)

    strategy, _ = _recommend(
        [tied_fulfillment_cheap, tied_fulfillment_expensive], objective="maximize_service_level"
    )

    assert strategy == "cheap"
