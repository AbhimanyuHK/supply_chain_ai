import datetime

import pytest

from app.agents.constraint_validation_agent import route_after_validation, validate_constraints_node
from app.core.business_rules import BusinessRules
from app.core.config import get_settings
from app.models.entities import LocationType
from app.schemas.allocation import AllocationLine, AllocationResult, AllocationScenario
from app.schemas.constraint_validation import ConstraintValidationResult
from app.schemas.cost_optimization import CostedLine, CostOptimizationResult, ScenarioCostSummary
from app.schemas.inventory import InventoryRead
from app.schemas.inventory_analysis import InventoryAnalysisRecord, InventoryAnalysisResult
from app.schemas.planning import MasterDataSnapshot
from app.schemas.product import ProductRead
from app.schemas.store import StoreRead
from app.schemas.terminal import TerminalRead

BUSINESS_RULES = BusinessRules(
    min_shipment_qty=1,
    max_shipment_qty_per_product=100,
    max_lead_time_days=2,
)


def _snapshot(store_capacity=1000, terminal_capacity=100000, terminal_available_qty=1000) -> MasterDataSnapshot:
    return MasterDataSnapshot(
        stores=[StoreRead(store_id=1, store_name="S1", latitude=0, longitude=0, capacity=store_capacity, priority=1)],
        terminals=[
            TerminalRead(terminal_id=1, terminal_name="T1", latitude=0, longitude=0, capacity=terminal_capacity)
        ],
        products=[ProductRead(product_id=1, sku="SKU-1", name="P", category="C", weight=1, volume=1, cost=10)],
        inventory=[
            InventoryRead(
                inventory_id=1, location_type=LocationType.TERMINAL, location_id=1, product_id=1,
                available_qty=terminal_available_qty, reserved_qty=0, incoming_qty=0, damaged_qty=0,
            )
        ],
        demand_history=[],
        fleet=[],
        distance_matrix=[],
        business_rules=BUSINESS_RULES,
        loaded_at=datetime.datetime.now(datetime.timezone.utc),
    )


def _line(quantity=10, delivery_hours=1.0) -> AllocationLine:
    return AllocationLine(
        terminal_id=1, store_id=1, product_id=1, quantity=quantity,
        estimated_transport_cost=100.0, estimated_delivery_hours=delivery_hours,
    )


def _scenario(strategy, lines, hp_fulfilled=1, hp_total=1) -> AllocationScenario:
    return AllocationScenario(
        strategy=strategy, lines=lines, total_quantity_allocated=sum(l.quantity for l in lines),
        total_shortage_quantity=sum(l.quantity for l in lines), fulfillment_rate=1.0,
        total_estimated_cost=100.0, high_priority_shortages_fulfilled=hp_fulfilled,
        high_priority_shortages_total=hp_total, rank=1, rationale="test",
    )


def _cost_summary(strategy, lines, total_cost=100.0, hp_fulfilled=1, hp_total=1) -> ScenarioCostSummary:
    costed = [
        CostedLine(
            terminal_id=l.terminal_id, store_id=l.store_id, product_id=l.product_id, quantity=l.quantity,
            vehicle_id=None, transportation_cost=10.0, handling_cost=1.0, holding_cost=1.0, delay_penalty=0.0,
            total_cost=12.0, vehicle_capacity_exceeded=False,
        )
        for l in lines
    ]
    return ScenarioCostSummary(
        strategy=strategy, lines=costed, total_transportation_cost=10.0, total_handling_cost=1.0,
        total_holding_cost=1.0, total_delay_penalty=0.0, total_cost=total_cost,
        high_priority_shortages_fulfilled=hp_fulfilled, high_priority_shortages_total=hp_total,
        fully_satisfies_high_priority=(hp_fulfilled == hp_total), fulfillment_rate=1.0,
    )


def _inventory_records(store_on_hand=0, terminal_on_hand=1000) -> list[InventoryAnalysisRecord]:
    return [
        InventoryAnalysisRecord(
            location_type=LocationType.STORE, location_id=1, product_id=1, on_hand_qty=store_on_hand,
            available_qty=store_on_hand, reserved_qty=0, incoming_qty=0, damaged_qty=0,
        ),
        InventoryAnalysisRecord(
            location_type=LocationType.TERMINAL, location_id=1, product_id=1, on_hand_qty=terminal_on_hand,
            available_qty=terminal_on_hand, reserved_qty=0, incoming_qty=0, damaged_qty=0,
        ),
    ]


async def _state(scenarios, cost_summaries, recommended, inventory_records=None, replanning_attempts=0, snapshot=None):
    return {
        "master_data": snapshot or _snapshot(),
        "inventory_analysis": InventoryAnalysisResult(
            records=inventory_records or _inventory_records(), shortages=[]
        ),
        "allocation": AllocationResult(scenarios=scenarios, recommended_strategy=recommended),
        "cost_optimization": CostOptimizationResult(
            scenarios=cost_summaries, recommended_strategy=recommended, recommendation_rationale="test"
        ),
        "replanning_attempts": replanning_attempts,
    }


@pytest.mark.asyncio
async def test_valid_scenario_passes_and_is_carried_forward():
    lines = [_line(quantity=10, delivery_hours=1.0)]
    scenario = _scenario("priority_first", lines)
    cost_summary = _cost_summary("priority_first", lines)
    state = await _state([scenario], [cost_summary], "priority_first")

    update = await validate_constraints_node(state)
    result: ConstraintValidationResult = update["constraint_validation"]

    assert result.scenario_validations[0].is_valid
    assert result.final_strategy == "priority_first"
    assert result.unresolved_violations == []
    assert result.replanning_triggered is False
    assert "replanning_attempts" not in update


@pytest.mark.asyncio
async def test_max_shipment_qty_violation_detected():
    lines = [_line(quantity=500)]  # exceeds max_shipment_qty_per_product=100
    scenario = _scenario("priority_first", lines)
    cost_summary = _cost_summary("priority_first", lines)
    state = await _state([scenario], [cost_summary], "priority_first")

    update = await validate_constraints_node(state)
    result: ConstraintValidationResult = update["constraint_validation"]

    assert not result.scenario_validations[0].is_valid
    assert any(v.constraint == "max_shipment_qty" for v in result.scenario_validations[0].violations)


@pytest.mark.asyncio
async def test_available_inventory_violation_when_lines_exceed_terminal_stock():
    # Two lines from the same terminal/product summing beyond what's actually available.
    lines = [_line(quantity=60), AllocationLine(
        terminal_id=1, store_id=1, product_id=1, quantity=60,
        estimated_transport_cost=100.0, estimated_delivery_hours=1.0,
    )]
    scenario = _scenario("priority_first", lines)
    cost_summary = _cost_summary("priority_first", lines)
    snapshot = _snapshot(terminal_available_qty=100)  # 60+60=120 > 100 available
    state = await _state([scenario], [cost_summary], "priority_first", snapshot=snapshot)

    update = await validate_constraints_node(state)
    result: ConstraintValidationResult = update["constraint_validation"]

    assert any(v.constraint == "available_inventory" for v in result.scenario_validations[0].violations)


@pytest.mark.asyncio
async def test_store_capacity_violation_when_projected_stock_exceeds_capacity():
    lines = [_line(quantity=50)]
    scenario = _scenario("priority_first", lines)
    cost_summary = _cost_summary("priority_first", lines)
    snapshot = _snapshot(store_capacity=60)
    records = _inventory_records(store_on_hand=20)  # 20 + 50 = 70 > 60 capacity
    state = await _state([scenario], [cost_summary], "priority_first", inventory_records=records, snapshot=snapshot)

    update = await validate_constraints_node(state)
    result: ConstraintValidationResult = update["constraint_validation"]

    assert any(v.constraint == "store_capacity" for v in result.scenario_validations[0].violations)


@pytest.mark.asyncio
async def test_terminal_capacity_violation_when_terminal_already_over_capacity():
    lines = [_line(quantity=10)]
    scenario = _scenario("priority_first", lines)
    cost_summary = _cost_summary("priority_first", lines)
    snapshot = _snapshot(terminal_capacity=500)
    records = _inventory_records(terminal_on_hand=600)  # already over the 500 capacity
    state = await _state([scenario], [cost_summary], "priority_first", inventory_records=records, snapshot=snapshot)

    update = await validate_constraints_node(state)
    result: ConstraintValidationResult = update["constraint_validation"]

    assert any(v.constraint == "terminal_capacity" for v in result.scenario_validations[0].violations)


@pytest.mark.asyncio
async def test_lead_time_violation_when_delivery_exceeds_max():
    lines = [_line(quantity=10, delivery_hours=1000.0)]  # way beyond max_lead_time_days=2 (48h)
    scenario = _scenario("priority_first", lines)
    cost_summary = _cost_summary("priority_first", lines)
    state = await _state([scenario], [cost_summary], "priority_first")

    update = await validate_constraints_node(state)
    result: ConstraintValidationResult = update["constraint_validation"]

    assert any(v.constraint == "lead_time" for v in result.scenario_validations[0].violations)


@pytest.mark.asyncio
async def test_business_priority_violation_when_high_priority_not_fully_covered():
    lines = [_line(quantity=10)]
    scenario = _scenario("priority_first", lines, hp_fulfilled=0, hp_total=1)
    cost_summary = _cost_summary("priority_first", lines, hp_fulfilled=0, hp_total=1)
    state = await _state([scenario], [cost_summary], "priority_first")

    update = await validate_constraints_node(state)
    result: ConstraintValidationResult = update["constraint_validation"]

    assert any(v.constraint == "business_priority" for v in result.scenario_validations[0].violations)


@pytest.mark.asyncio
async def test_switches_to_valid_alternative_when_recommended_fails():
    bad_lines = [_line(quantity=500)]  # violates max_shipment_qty
    good_lines = [_line(quantity=10)]
    bad_scenario = _scenario("priority_first", bad_lines)
    good_scenario = _scenario("score_first", good_lines)
    bad_cost = _cost_summary("priority_first", bad_lines, total_cost=50.0)
    good_cost = _cost_summary("score_first", good_lines, total_cost=999.0)  # more expensive but valid
    state = await _state([bad_scenario, good_scenario], [bad_cost, good_cost], "priority_first")

    update = await validate_constraints_node(state)
    result: ConstraintValidationResult = update["constraint_validation"]

    assert result.final_strategy == "score_first"
    assert result.unresolved_violations == []
    assert result.replanning_triggered is False


@pytest.mark.asyncio
async def test_triggers_replanning_when_no_scenario_valid_and_attempts_remain():
    lines = [_line(quantity=500)]
    scenario = _scenario("priority_first", lines)
    cost_summary = _cost_summary("priority_first", lines)
    max_attempts = get_settings().max_replanning_attempts
    state = await _state([scenario], [cost_summary], "priority_first", replanning_attempts=0)
    assert max_attempts > 0

    update = await validate_constraints_node(state)
    result: ConstraintValidationResult = update["constraint_validation"]

    assert result.replanning_triggered is True
    assert update["replanning_attempts"] == 1
    assert result.unresolved_violations  # carried for Supply Planning's retry prompt
    assert route_after_validation({"constraint_validation": result}) == "replan"


@pytest.mark.asyncio
async def test_gives_up_after_max_replanning_attempts():
    lines = [_line(quantity=500)]
    scenario = _scenario("priority_first", lines)
    cost_summary = _cost_summary("priority_first", lines)
    max_attempts = get_settings().max_replanning_attempts
    state = await _state([scenario], [cost_summary], "priority_first", replanning_attempts=max_attempts)

    update = await validate_constraints_node(state)
    result: ConstraintValidationResult = update["constraint_validation"]

    assert result.replanning_triggered is False
    assert result.final_strategy == "priority_first"
    assert result.unresolved_violations
    assert "replanning_attempts" not in update
    assert update["errors"]
    assert route_after_validation({"constraint_validation": result}) == "end"


@pytest.mark.asyncio
async def test_skips_when_no_allocation_scenarios():
    state = {
        "master_data": _snapshot(),
        "allocation": AllocationResult(scenarios=[], recommended_strategy=None),
        "cost_optimization": CostOptimizationResult(scenarios=[], recommended_strategy=None, recommendation_rationale="none"),
    }

    update = await validate_constraints_node(state)
    result: ConstraintValidationResult = update["constraint_validation"]

    assert result.scenario_validations == []
    assert result.final_strategy is None
    assert route_after_validation({"constraint_validation": result}) == "end"


def test_route_after_validation_defaults_to_end_when_no_validation_yet():
    assert route_after_validation({}) == "end"
