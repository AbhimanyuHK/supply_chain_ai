"""Final Recommendation Agent — ninth LangGraph node, and the last Phase 1
agent in the spec's 13-agent list.

Synthesizes everything the earlier eight nodes computed into the spec's
exact output shape: shipment plan, business explanation, risk assessment,
alternative recommendations, confidence score, expected inventory after
shipment, expected service level.

Almost everything here is deterministic, reusing data already computed by
earlier agents rather than re-deriving or re-explaining it (each piece is
its own testable function below, not inlined, precisely so it can be
verified without needing a live Groq call):
  - `_build_shipment_plan`: per-line cost breakdown from Module 7's
    `CostedLine`s for the selected scenario, plus each line's explanation
    reused from Module 5's own rationale for that exact (terminal, store,
    product) candidate - not a fresh LLM call per line.
  - `_compute_expected_inventory`: plain arithmetic against the master data
    snapshot's current stock.
  - `_build_alternatives`: the other scenarios Module 9 already scored,
    with a one-line deterministic reason (lower score) for why they weren't
    picked.

The one thing that's a genuine synthesis task - turning a handful of real
metrics into a coherent business explanation, risk assessment, and
contingency plan, calibrating a confidence score - goes to the configured
reasoning engine (Groq or local Ollama - see `app/core/llm.py`; this is the
workflow's fourth LLM call), because writing prose from real numbers is
exactly the kind of task an LLM is good at and arithmetic isn't.
"""

from collections import defaultdict
from functools import lru_cache

from loguru import logger
from pydantic import BaseModel, Field

from app.agents.state import PlanningState
from app.core.llm import get_chat_model
from app.models.entities import LocationType
from app.schemas.allocation import AllocationScenario
from app.schemas.cost_optimization import ScenarioCostSummary
from app.schemas.decision_review import DecisionReviewResult
from app.schemas.eta_prediction import ETAPredictionResult
from app.schemas.final_recommendation import (
    AlternativeRecommendation,
    FinalRecommendation,
    InventoryProjection,
    ShipmentPlanLine,
)
from app.schemas.fleet_assignment import FleetAssignmentResult
from app.schemas.planning import MasterDataSnapshot
from app.schemas.route_planning import RoutePlanningResult
from app.schemas.supply_planning import CandidatePlan


class _LLMFinalSynthesis(BaseModel):
    business_explanation: str
    risk_assessment: str
    contingency_actions: list[str]
    confidence_score: float = Field(ge=0, le=100)


@lru_cache
def _get_structured_llm():
    return get_chat_model().with_structured_output(_LLMFinalSynthesis)


def _fleet_route_eta_enrichment(
    strategy: str,
    fleet_assignment: FleetAssignmentResult | None,
    route_planning: RoutePlanningResult | None,
    eta_prediction: ETAPredictionResult | None,
) -> dict[tuple[int, int, int], tuple[int | None, int | None, float | None]]:
    """Maps (terminal_id, store_id, product_id) -> (vehicle_id, route_sequence,
    predicted_eta_hours) for the selected scenario. All `None` when the fleet
    module is disabled (`fleet_assignment` is `None`) or a line has no
    matching Phase 2 data (e.g. Fleet Assignment couldn't assign it a vehicle).
    """
    if fleet_assignment is None:
        return {}

    scenario_assignment = next(
        (sa for sa in fleet_assignment.scenario_assignments if sa.strategy == strategy), None
    )
    if scenario_assignment is None:
        return {}

    sequence_by_vehicle_store: dict[tuple[int, int], int] = {}
    if route_planning is not None:
        scenario_route = next((sr for sr in route_planning.scenario_routes if sr.strategy == strategy), None)
        if scenario_route is not None:
            for route in scenario_route.vehicle_routes:
                for stop in route.stops:
                    sequence_by_vehicle_store[(route.vehicle_id, stop.store_id)] = stop.sequence

    eta_by_vehicle_store: dict[tuple[int, int], float] = {}
    if eta_prediction is not None:
        scenario_prediction = next(
            (sp for sp in eta_prediction.scenario_predictions if sp.strategy == strategy), None
        )
        if scenario_prediction is not None:
            for stop_eta in scenario_prediction.stop_etas:
                eta_by_vehicle_store[(stop_eta.vehicle_id, stop_eta.store_id)] = stop_eta.predicted_eta_hours

    enrichment: dict[tuple[int, int, int], tuple[int | None, int | None, float | None]] = {}
    for vehicle_load in scenario_assignment.vehicle_loads:
        for line in vehicle_load.lines:
            key = (line.terminal_id, line.store_id, line.product_id)
            vehicle_store_key = (vehicle_load.vehicle_id, line.store_id)
            enrichment[key] = (
                vehicle_load.vehicle_id,
                sequence_by_vehicle_store.get(vehicle_store_key),
                eta_by_vehicle_store.get(vehicle_store_key),
            )
    return enrichment


def _build_shipment_plan(
    scenario: AllocationScenario,
    cost_summary: ScenarioCostSummary,
    candidate_plans: list[CandidatePlan],
    fleet_route_eta_by_key: dict[tuple[int, int, int], tuple[int | None, int | None, float | None]],
) -> list[ShipmentPlanLine]:
    cost_line_by_key = {(c.terminal_id, c.store_id, c.product_id): c for c in cost_summary.lines}
    rationale_by_key: dict[tuple[int, int, int], str] = {}
    for plan in candidate_plans:
        rationale_by_key.setdefault((plan.terminal_id, plan.store_id, plan.product_id), plan.rationale)

    shipment_plan = []
    for line in scenario.lines:
        key = (line.terminal_id, line.store_id, line.product_id)
        cost_line = cost_line_by_key.get(key)
        vehicle_id, route_sequence, predicted_eta_hours = fleet_route_eta_by_key.get(key, (None, None, None))
        shipment_plan.append(
            ShipmentPlanLine(
                terminal_id=line.terminal_id,
                store_id=line.store_id,
                product_id=line.product_id,
                quantity=line.quantity,
                transportation_cost=cost_line.transportation_cost if cost_line else 0.0,
                handling_cost=cost_line.handling_cost if cost_line else 0.0,
                holding_cost=cost_line.holding_cost if cost_line else 0.0,
                delay_penalty=cost_line.delay_penalty if cost_line else 0.0,
                total_cost=cost_line.total_cost if cost_line else 0.0,
                estimated_delivery_hours=line.estimated_delivery_hours,
                explanation=rationale_by_key.get(
                    key, "Selected as part of the recommended allocation strategy."
                ),
                vehicle_id=vehicle_id,
                route_sequence=route_sequence,
                predicted_eta_hours=predicted_eta_hours,
            )
        )
    return shipment_plan


def _compute_expected_inventory(
    scenario: AllocationScenario, snapshot: MasterDataSnapshot
) -> list[InventoryProjection]:
    shipped_by_terminal_product: dict[tuple[int, int], int] = defaultdict(int)
    shipped_by_store_product: dict[tuple[int, int], int] = defaultdict(int)
    for line in scenario.lines:
        shipped_by_terminal_product[(line.terminal_id, line.product_id)] += line.quantity
        shipped_by_store_product[(line.store_id, line.product_id)] += line.quantity

    expected_inventory: list[InventoryProjection] = []
    for inv in snapshot.inventory:
        if inv.location_type == LocationType.TERMINAL:
            shipped = shipped_by_terminal_product.get((inv.location_id, inv.product_id), 0)
            if shipped:
                expected_inventory.append(
                    InventoryProjection(
                        location_type=inv.location_type,
                        location_id=inv.location_id,
                        product_id=inv.product_id,
                        before_qty=inv.available_qty,
                        after_qty=inv.available_qty - shipped,
                    )
                )
        else:
            shipped = shipped_by_store_product.get((inv.location_id, inv.product_id), 0)
            if shipped:
                expected_inventory.append(
                    InventoryProjection(
                        location_type=inv.location_type,
                        location_id=inv.location_id,
                        product_id=inv.product_id,
                        before_qty=inv.available_qty,
                        after_qty=inv.available_qty + shipped,
                    )
                )
    return expected_inventory


def _build_alternatives(
    decision_review: DecisionReviewResult, selected_strategy: str
) -> list[AlternativeRecommendation]:
    selected_evaluation = next(e for e in decision_review.evaluations if e.strategy == selected_strategy)
    return [
        AlternativeRecommendation(
            strategy=evaluation.strategy,
            overall_score=evaluation.overall_score,
            total_cost=evaluation.total_cost,
            fulfillment_rate=evaluation.demand_fulfillment_rate,
            high_priority_shortages_fulfilled=evaluation.high_priority_shortages_fulfilled,
            high_priority_shortages_total=evaluation.high_priority_shortages_total,
            reason_not_selected=(
                f"Lower overall score ({evaluation.overall_score:.0f}) than the selected "
                f"'{selected_strategy}' plan ({selected_evaluation.overall_score:.0f})."
            ),
        )
        for evaluation in decision_review.evaluations
        if evaluation.strategy != selected_strategy
    ]


def _build_prompt(
    strategy: str,
    evaluation,
    fell_back: bool,
    unresolved_violation_count: int,
    unresolved_shortage_count: int,
    objective: str = "minimize_cost",
) -> str:
    objective_note = (
        "This run's business objective was to maximize service level (fulfillment), "
        "with cost as a secondary concern."
        if objective == "maximize_service_level"
        else "This run's business objective was to minimize cost, subject to fully "
        "covering high-priority stores."
    )
    return (
        f"A supply chain shipment plan ('{strategy}' strategy) has been selected with these "
        f"real, already-computed metrics ({objective_note}):\n"
        f"- Overall review score: {evaluation.overall_score:.0f}/100\n"
        f"- Demand fulfillment rate: {evaluation.demand_fulfillment_rate:.0%}\n"
        f"- High-priority stores covered: {evaluation.high_priority_shortages_fulfilled}/"
        f"{evaluation.high_priority_shortages_total}\n"
        f"- Inventory balance score: {evaluation.inventory_balance_score:.2f} (0-1, higher=better)\n"
        f"- Future inventory risk: {evaluation.future_inventory_risk_ratio:.2f} (0-1, lower=better)\n"
        f"- Total transportation distance: {evaluation.total_transportation_distance_km:.1f} km\n"
        f"- Total cost: {evaluation.total_cost:.2f}\n"
        f"- Fell back to a best-effort (constraint-violating) plan: {fell_back}\n"
        f"- Unresolved constraint violations remaining: {unresolved_violation_count}\n"
        f"- Shortages with no candidate terminal at all (unfulfillable): {unresolved_shortage_count}\n"
        f"- Shipment lines flagged at elevated delivery risk (tight lead time, an "
        f"overloaded vehicle, or a scenario that already needed replanning once): "
        f"{evaluation.at_risk_stops_count}\n\n"
        "Write: (1) a short 2-3 sentence business explanation of why this plan is "
        "recommended, in the style of 'Store X will receive Y units of Z because it "
        "minimizes distance, satisfies demand, and reduces logistics cost'; (2) a short "
        "risk assessment paragraph covering the real risks above; (3) 2-4 short recommended "
        "contingency actions if those risks materialize; (4) a 0-100 confidence score - "
        "reduce it noticeably if the plan fell back to a constraint-violating option, has "
        "unresolved violations, leaves unfulfillable shortages, or has shipment lines "
        "flagged at elevated delivery risk."
    )


async def recommend_final_node(state: PlanningState) -> dict:
    decision_review = state["decision_review"]

    if not decision_review.evaluations or decision_review.selected_strategy is None:
        message = "No reviewed scenario to recommend - skipped"
        logger.info(message)
        result = FinalRecommendation(
            selected_strategy=None,
            shipment_plan=[],
            expected_total_cost=0.0,
            expected_service_level=0.0,
            expected_inventory_after_shipment=[],
            alternative_recommendations=[],
            business_explanation=message,
            risk_assessment="",
            contingency_actions=[],
            confidence_score=0.0,
            fell_back_to_invalid_scenario=False,
            unresolved_shortages_count=0,
        )
        return {"final_recommendation": result, "trace": [message]}

    allocation = state["allocation"]
    cost_optimization = state["cost_optimization"]
    constraint_validation = state["constraint_validation"]
    supply_planning = state["supply_planning"]
    snapshot = state["master_data"]

    selected_strategy = decision_review.selected_strategy
    selected_scenario = next(s for s in allocation.scenarios if s.strategy == selected_strategy)
    selected_cost = next(s for s in cost_optimization.scenarios if s.strategy == selected_strategy)
    selected_evaluation = next(e for e in decision_review.evaluations if e.strategy == selected_strategy)

    fleet_route_eta_by_key = _fleet_route_eta_enrichment(
        selected_strategy, state.get("fleet_assignment"), state.get("route_planning"), state.get("eta_prediction")
    )
    shipment_plan = _build_shipment_plan(
        selected_scenario, selected_cost, supply_planning.candidate_plans, fleet_route_eta_by_key
    )
    expected_inventory = _compute_expected_inventory(selected_scenario, snapshot)
    alternatives = _build_alternatives(decision_review, selected_strategy)

    unresolved_violation_count = len(constraint_validation.unresolved_violations)
    unresolved_shortage_count = len(supply_planning.unresolved_shortages)

    structured_llm = _get_structured_llm()
    synthesis: _LLMFinalSynthesis = await structured_llm.ainvoke(
        _build_prompt(
            selected_strategy,
            selected_evaluation,
            decision_review.fell_back_to_invalid_scenario,
            unresolved_violation_count,
            unresolved_shortage_count,
            state["request"].optimization_objective,
        )
    )

    result = FinalRecommendation(
        selected_strategy=selected_strategy,
        shipment_plan=shipment_plan,
        expected_total_cost=selected_cost.total_cost,
        expected_service_level=selected_scenario.fulfillment_rate,
        expected_inventory_after_shipment=expected_inventory,
        alternative_recommendations=alternatives,
        business_explanation=synthesis.business_explanation,
        risk_assessment=synthesis.risk_assessment,
        contingency_actions=synthesis.contingency_actions,
        confidence_score=synthesis.confidence_score,
        fell_back_to_invalid_scenario=decision_review.fell_back_to_invalid_scenario,
        unresolved_shortages_count=unresolved_shortage_count,
    )

    message = (
        f"Final recommendation: '{selected_strategy}' ({len(shipment_plan)} shipment lines, "
        f"confidence {synthesis.confidence_score:.0f})"
    )
    logger.info(message)

    return {"final_recommendation": result, "trace": [message]}
