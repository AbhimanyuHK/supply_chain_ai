import datetime

import pytest

from app.agents.decision_review_agent import (
    _future_inventory_risk_ratio,
    _inventory_balance_score,
    _total_distance_km,
    review_decision_node,
)
from app.core.business_rules import BusinessRules
from app.models.entities import LocationType
from app.schemas.allocation import AllocationLine, AllocationResult, AllocationScenario
from app.schemas.constraint_validation import ConstraintValidationResult, ScenarioValidation
from app.schemas.cost_optimization import CostedLine, CostOptimizationResult, ScenarioCostSummary
from app.schemas.decision_review import DecisionReviewResult
from app.schemas.distance import DistanceMatrixRead
from app.schemas.inventory import InventoryRead
from app.schemas.planning import MasterDataSnapshot
from app.schemas.product import ProductRead
from app.schemas.store import StoreRead
from app.schemas.terminal import TerminalRead
from tests.conftest import requires_llm_configured as requires_groq_key


def _line(terminal_id=1, store_id=1, product_id=1, quantity=10) -> AllocationLine:
    return AllocationLine(
        terminal_id=terminal_id, store_id=store_id, product_id=product_id, quantity=quantity,
        estimated_transport_cost=10.0, estimated_delivery_hours=1.0,
    )


def test_inventory_balance_score_is_1_when_fewer_than_2_points():
    assert _inventory_balance_score([_line()], {(1, 1): 100}) == 1.0
    assert _inventory_balance_score([], {}) == 1.0


def test_inventory_balance_score_lower_when_draw_down_uneven():
    lines_even = [_line(terminal_id=1, quantity=50), _line(terminal_id=2, quantity=50)]
    stock_even = {(1, 1): 100, (2, 1): 100}  # both drawn down 50%

    lines_uneven = [_line(terminal_id=1, quantity=90), _line(terminal_id=2, quantity=10)]
    stock_uneven = {(1, 1): 100, (2, 1): 100}  # 90% vs 10%

    even_score = _inventory_balance_score(lines_even, stock_even)
    uneven_score = _inventory_balance_score(lines_uneven, stock_uneven)

    assert even_score == 1.0
    assert uneven_score < even_score


def test_future_inventory_risk_flags_drained_terminals():
    lines = [_line(terminal_id=1, quantity=95), _line(terminal_id=2, quantity=5)]
    stock = {(1, 1): 100, (2, 1): 100}  # terminal 1 left at 5%, terminal 2 left at 95%

    risk = _future_inventory_risk_ratio(lines, stock, threshold=0.1)

    assert risk == 0.5  # 1 of 2 (terminal, product) pairs drained below 10%


def test_future_inventory_risk_zero_when_nothing_shipped():
    assert _future_inventory_risk_ratio([], {}, threshold=0.1) == 0.0


def test_total_distance_km_sums_per_line():
    lines = [_line(terminal_id=1, store_id=1), _line(terminal_id=2, store_id=1)]
    distance_by_pair = {(1, 1): 10.0, (2, 1): 25.0}

    assert _total_distance_km(lines, distance_by_pair) == 35.0


def _snapshot() -> MasterDataSnapshot:
    return MasterDataSnapshot(
        stores=[StoreRead(store_id=1, store_name="S", latitude=0, longitude=0, capacity=1000, priority=1)],
        terminals=[TerminalRead(terminal_id=1, terminal_name="T", latitude=0, longitude=0, capacity=1000)],
        products=[ProductRead(product_id=1, sku="SKU-1", name="P", category="C", weight=1, volume=1, cost=10)],
        inventory=[
            InventoryRead(
                inventory_id=1, location_type=LocationType.TERMINAL, location_id=1, product_id=1,
                available_qty=100, reserved_qty=0, incoming_qty=0, damaged_qty=0,
            )
        ],
        demand_history=[],
        fleet=[],
        distance_matrix=[DistanceMatrixRead(terminal_id=1, store_id=1, distance_km=10.0, travel_time=1.0)],
        business_rules=BusinessRules(),
        loaded_at=datetime.datetime.now(datetime.timezone.utc),
    )


def _scenario(strategy: str, quantity: int, hp_fulfilled=1, hp_total=1) -> AllocationScenario:
    return AllocationScenario(
        strategy=strategy, lines=[_line(quantity=quantity)], total_quantity_allocated=quantity,
        total_shortage_quantity=quantity, fulfillment_rate=1.0, total_estimated_cost=50.0,
        high_priority_shortages_fulfilled=hp_fulfilled, high_priority_shortages_total=hp_total,
        rank=1, rationale="test",
    )


def _cost_summary(strategy: str, quantity: int, total_cost: float, hp_fulfilled=1, hp_total=1) -> ScenarioCostSummary:
    line = CostedLine(
        terminal_id=1, store_id=1, product_id=1, quantity=quantity, vehicle_id=None,
        transportation_cost=total_cost, handling_cost=0, holding_cost=0, delay_penalty=0,
        total_cost=total_cost, vehicle_capacity_exceeded=False,
    )
    return ScenarioCostSummary(
        strategy=strategy, lines=[line], total_transportation_cost=total_cost, total_handling_cost=0,
        total_holding_cost=0, total_delay_penalty=0, total_cost=total_cost,
        high_priority_shortages_fulfilled=hp_fulfilled, high_priority_shortages_total=hp_total,
        fully_satisfies_high_priority=(hp_fulfilled == hp_total),
    )


@pytest.mark.asyncio
async def test_skips_when_no_scenarios():
    state = {"allocation": AllocationResult(scenarios=[], recommended_strategy=None)}

    update = await review_decision_node(state)
    result: DecisionReviewResult = update["decision_review"]

    assert result.evaluations == []
    assert result.selected_strategy is None
    assert result.fell_back_to_invalid_scenario is False


@requires_groq_key
@pytest.mark.asyncio
async def test_only_valid_scenarios_are_reviewed_and_best_is_selected():
    good = _scenario("priority_first", quantity=10)
    bad = _scenario("score_first", quantity=10)
    good_cost = _cost_summary("priority_first", 10, total_cost=100.0)
    bad_cost = _cost_summary("score_first", 10, total_cost=50.0)  # cheaper but invalid

    state = {
        "master_data": _snapshot(),
        "allocation": AllocationResult(scenarios=[good, bad], recommended_strategy="score_first"),
        "cost_optimization": CostOptimizationResult(
            scenarios=[good_cost, bad_cost], recommended_strategy="score_first", recommendation_rationale="test"
        ),
        "constraint_validation": ConstraintValidationResult(
            scenario_validations=[
                ScenarioValidation(strategy="priority_first", violations=[], is_valid=True),
                ScenarioValidation(strategy="score_first", violations=[], is_valid=False),
            ],
            final_strategy="score_first",
            unresolved_violations=[],
            replanning_triggered=False,
        ),
    }

    update = await review_decision_node(state)
    result: DecisionReviewResult = update["decision_review"]

    # Only the valid scenario should even be evaluated.
    assert len(result.evaluations) == 1
    assert result.evaluations[0].strategy == "priority_first"
    assert result.selected_strategy == "priority_first"
    assert result.fell_back_to_invalid_scenario is False
    assert 0 <= result.evaluations[0].overall_score <= 100
    assert result.evaluations[0].rationale


@requires_groq_key
@pytest.mark.asyncio
async def test_falls_back_to_best_effort_scenario_when_none_valid():
    only = _scenario("priority_first", quantity=10)
    only_cost = _cost_summary("priority_first", 10, total_cost=100.0)

    state = {
        "master_data": _snapshot(),
        "allocation": AllocationResult(scenarios=[only], recommended_strategy="priority_first"),
        "cost_optimization": CostOptimizationResult(
            scenarios=[only_cost], recommended_strategy="priority_first", recommendation_rationale="test"
        ),
        "constraint_validation": ConstraintValidationResult(
            scenario_validations=[ScenarioValidation(strategy="priority_first", violations=[], is_valid=False)],
            final_strategy="priority_first",
            unresolved_violations=[],
            replanning_triggered=False,
        ),
    }

    update = await review_decision_node(state)
    result: DecisionReviewResult = update["decision_review"]

    assert result.fell_back_to_invalid_scenario is True
    assert result.selected_strategy == "priority_first"
    assert "no scenario passed constraint validation" in result.selection_rationale.lower()
