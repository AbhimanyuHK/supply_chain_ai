import datetime

import pytest

from app.agents.final_recommendation_agent import (
    _build_alternatives,
    _build_shipment_plan,
    _compute_expected_inventory,
    recommend_final_node,
)
from app.core.business_rules import BusinessRules
from app.models.entities import LocationType
from app.schemas.allocation import AllocationLine, AllocationResult, AllocationScenario
from app.schemas.constraint_validation import ConstraintValidationResult, ScenarioValidation
from app.schemas.cost_optimization import CostedLine, CostOptimizationResult, ScenarioCostSummary
from app.schemas.decision_review import DecisionReviewResult, ScenarioEvaluation
from app.schemas.final_recommendation import FinalRecommendation
from app.schemas.inventory import InventoryRead
from app.schemas.planning import MasterDataSnapshot
from app.schemas.product import ProductRead
from app.schemas.store import StoreRead
from app.schemas.supply_planning import CandidatePlan, SupplyPlanningResult
from app.schemas.terminal import TerminalRead
from tests.conftest import requires_llm_configured as requires_groq_key


def _line(terminal_id=1, store_id=1, product_id=1, quantity=10) -> AllocationLine:
    return AllocationLine(
        terminal_id=terminal_id, store_id=store_id, product_id=product_id, quantity=quantity,
        estimated_transport_cost=50.0, estimated_delivery_hours=2.0,
    )


def _scenario(strategy: str, lines: list[AllocationLine], hp_fulfilled=1, hp_total=1) -> AllocationScenario:
    total_qty = sum(l.quantity for l in lines)
    return AllocationScenario(
        strategy=strategy, lines=lines, total_quantity_allocated=total_qty, total_shortage_quantity=total_qty,
        fulfillment_rate=1.0, total_estimated_cost=100.0, high_priority_shortages_fulfilled=hp_fulfilled,
        high_priority_shortages_total=hp_total, rank=1, rationale="test",
    )


def _cost_summary(strategy: str, lines: list[AllocationLine], total_cost: float) -> ScenarioCostSummary:
    costed = [
        CostedLine(
            terminal_id=l.terminal_id, store_id=l.store_id, product_id=l.product_id, quantity=l.quantity,
            vehicle_id=1, transportation_cost=40.0, handling_cost=5.0, holding_cost=2.0, delay_penalty=0.0,
            total_cost=47.0, vehicle_capacity_exceeded=False,
        )
        for l in lines
    ]
    return ScenarioCostSummary(
        strategy=strategy, lines=costed, total_transportation_cost=40.0, total_handling_cost=5.0,
        total_holding_cost=2.0, total_delay_penalty=0.0, total_cost=total_cost,
        high_priority_shortages_fulfilled=1, high_priority_shortages_total=1, fully_satisfies_high_priority=True,
    )


def _evaluation(strategy: str, score: float) -> ScenarioEvaluation:
    return ScenarioEvaluation(
        strategy=strategy, inventory_balance_score=1.0, total_transportation_distance_km=5.0,
        demand_fulfillment_rate=1.0, future_inventory_risk_ratio=0.0, total_cost=47.0,
        high_priority_shortages_fulfilled=1, high_priority_shortages_total=1,
        overall_score=score, rationale=f"{strategy} rationale",
    )


def test_build_shipment_plan_reuses_module5_rationale_and_module7_costs():
    lines = [_line(quantity=10)]
    scenario = _scenario("priority_first", lines)
    cost_summary = _cost_summary("priority_first", lines, total_cost=47.0)
    candidate = CandidatePlan(
        terminal_id=1, store_id=1, product_id=1, quantity=10, estimated_transport_cost=50.0,
        estimated_delivery_hours=2.0, rationale="Closest terminal with lowest cost.", score=95.0,
    )

    plan = _build_shipment_plan(scenario, cost_summary, [candidate])

    assert len(plan) == 1
    assert plan[0].explanation == "Closest terminal with lowest cost."
    assert plan[0].total_cost == 47.0
    assert plan[0].transportation_cost == 40.0


def test_build_shipment_plan_falls_back_to_generic_explanation_when_no_candidate_matches():
    lines = [_line(quantity=10)]
    scenario = _scenario("priority_first", lines)
    cost_summary = _cost_summary("priority_first", lines, total_cost=47.0)

    plan = _build_shipment_plan(scenario, cost_summary, candidate_plans=[])

    assert plan[0].explanation == "Selected as part of the recommended allocation strategy."


def _snapshot() -> MasterDataSnapshot:
    return MasterDataSnapshot(
        stores=[StoreRead(store_id=1, store_name="S", latitude=0, longitude=0, capacity=1000, priority=1)],
        terminals=[TerminalRead(terminal_id=1, terminal_name="T", latitude=0, longitude=0, capacity=1000)],
        products=[ProductRead(product_id=1, sku="SKU-1", name="P", category="C", weight=1, volume=1, cost=10)],
        inventory=[
            InventoryRead(
                inventory_id=1, location_type=LocationType.TERMINAL, location_id=1, product_id=1,
                available_qty=100, reserved_qty=0, incoming_qty=0, damaged_qty=0,
            ),
            InventoryRead(
                inventory_id=2, location_type=LocationType.STORE, location_id=1, product_id=1,
                available_qty=5, reserved_qty=0, incoming_qty=0, damaged_qty=0,
            ),
        ],
        demand_history=[], fleet=[], distance_matrix=[], business_rules=BusinessRules(),
        loaded_at=datetime.datetime.now(datetime.timezone.utc),
    )


def test_compute_expected_inventory_decrements_terminal_and_increments_store():
    lines = [_line(terminal_id=1, store_id=1, quantity=10)]
    scenario = _scenario("priority_first", lines)

    projections = _compute_expected_inventory(scenario, _snapshot())
    by_location = {(p.location_type, p.location_id): p for p in projections}

    terminal_proj = by_location[(LocationType.TERMINAL, 1)]
    assert terminal_proj.before_qty == 100
    assert terminal_proj.after_qty == 90

    store_proj = by_location[(LocationType.STORE, 1)]
    assert store_proj.before_qty == 5
    assert store_proj.after_qty == 15


def test_compute_expected_inventory_skips_untouched_locations():
    # Nothing shipped -> no projections at all.
    scenario = _scenario("priority_first", [])
    assert _compute_expected_inventory(scenario, _snapshot()) == []


def test_build_alternatives_excludes_selected_and_explains_lower_score():
    decision_review = DecisionReviewResult(
        evaluations=[_evaluation("priority_first", 90.0), _evaluation("score_first", 70.0)],
        selected_strategy="priority_first",
        selection_rationale="best",
        fell_back_to_invalid_scenario=False,
    )

    alternatives = _build_alternatives(decision_review, "priority_first")

    assert len(alternatives) == 1
    assert alternatives[0].strategy == "score_first"
    assert "70" in alternatives[0].reason_not_selected
    assert "90" in alternatives[0].reason_not_selected


@pytest.mark.asyncio
async def test_recommend_final_node_skips_when_nothing_selected():
    state = {
        "decision_review": DecisionReviewResult(
            evaluations=[], selected_strategy=None, selection_rationale="none", fell_back_to_invalid_scenario=False
        )
    }

    update = await recommend_final_node(state)
    result: FinalRecommendation = update["final_recommendation"]

    assert result.selected_strategy is None
    assert result.shipment_plan == []
    assert result.confidence_score == 0.0


@requires_groq_key
@pytest.mark.asyncio
async def test_recommend_final_node_synthesizes_full_recommendation():
    lines = [_line(quantity=10)]
    scenario = _scenario("priority_first", lines)
    cost_summary = _cost_summary("priority_first", lines, total_cost=47.0)
    evaluation = _evaluation("priority_first", 90.0)
    candidate = CandidatePlan(
        terminal_id=1, store_id=1, product_id=1, quantity=10, estimated_transport_cost=50.0,
        estimated_delivery_hours=2.0, rationale="Closest terminal with lowest cost.", score=95.0,
    )

    state = {
        "master_data": _snapshot(),
        "allocation": AllocationResult(scenarios=[scenario], recommended_strategy="priority_first"),
        "cost_optimization": CostOptimizationResult(
            scenarios=[cost_summary], recommended_strategy="priority_first", recommendation_rationale="test"
        ),
        "constraint_validation": ConstraintValidationResult(
            scenario_validations=[ScenarioValidation(strategy="priority_first", violations=[], is_valid=True)],
            final_strategy="priority_first",
            unresolved_violations=[],
            replanning_triggered=False,
        ),
        "decision_review": DecisionReviewResult(
            evaluations=[evaluation],
            selected_strategy="priority_first",
            selection_rationale="best",
            fell_back_to_invalid_scenario=False,
        ),
        "supply_planning": SupplyPlanningResult(candidate_plans=[candidate], unresolved_shortages=[]),
    }

    update = await recommend_final_node(state)
    result: FinalRecommendation = update["final_recommendation"]

    assert result.selected_strategy == "priority_first"
    assert result.expected_total_cost == 47.0
    assert result.expected_service_level == 1.0
    assert len(result.shipment_plan) == 1
    assert result.shipment_plan[0].explanation == "Closest terminal with lowest cost."
    assert len(result.expected_inventory_after_shipment) == 2
    assert result.alternative_recommendations == []
    assert result.business_explanation
    assert result.risk_assessment
    assert result.contingency_actions
    assert 0 <= result.confidence_score <= 100
