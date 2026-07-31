"""ETA Prediction / Exception Handling Agent — third and last of the new
Phase 2 nodes: `assign_fleet -> plan_route -> predict_eta -> review_decision`.

Scoped, per an explicit decision, to **planning-time risk flagging** - a
deterministic node that predicts realistic delivery ETAs and flags shipment
lines at elevated risk, computed once during this planning run. NOT
real-time reactive exception handling (a truck is actually delayed/damaged
after dispatch) - that would need genuinely new infrastructure this
platform doesn't have (shipment execution tracking, an event intake
endpoint, a background worker), a much larger, separate undertaking than a
single LangGraph node.

No LLM call: predicted ETA and risk flags come from real thresholds, not a
prose judgment. The one place an LLM gets involved is downstream -
`final_recommendation_agent.py`'s existing 4th LLM call is enriched with
this agent's `at_risk_count` as one more real data point for its business
narrative/contingency actions, rather than adding a competing 5th call here.

**Three real risk signals**, any of which flags a stop `at_risk`:
- Predicted ETA (cumulative real `travel_time_hours` along the route, plus
  `business_rules.eta_variance_buffer_pct`) exceeds
  `business_rules.max_lead_time_days * 24` - Constraint Validation only ever
  checked a single leg's time, so a stop late in a multi-drop route can
  breach this hard cap in a way Constraint Validation had no way to see.
- The assigned vehicle was flagged `vehicle_capacity_exceeded` by Cost
  Optimization for this scenario (matched by `vehicle_id` - an approximate
  signal, since Cost Optimization's `vehicle_id` is a per-line costing
  proxy that may legitimately differ from Fleet Assignment's real, binding
  assignment; still a real, meaningful correlation worth flagging).
- This run needed at least one replanning attempt (`state["replanning_attempts"]
  > 0`) - already borderline once. Deliberately NOT
  `constraint_validation.replanning_triggered`: that field is only ever `True`
  on the validate_constraints_node call that decides to loop back to Supply
  Planning (`route_after_validation` routes there precisely when it's `True`),
  so by construction it is always `False` on whichever call's result actually
  reaches this node - `replanning_attempts` is the field that survives the
  loop and reflects the run's real history.
"""

from loguru import logger

from app.agents.state import PlanningState
from app.core.business_rules import BusinessRules
from app.schemas.cost_optimization import CostOptimizationResult
from app.schemas.eta_prediction import ETAPredictionResult, ScenarioETAPrediction, StopETA
from app.schemas.route_planning import ScenarioRoutePlan, VehicleRoute

_CONTINGENCY_BY_REASON = {
    "exceeds_max_lead_time": "Expedite or re-source from a closer terminal.",
    "vehicle_capacity_exceeded": "Split this shipment across an additional vehicle.",
    "replanning_triggered": "Monitor closely - this scenario already needed replanning once.",
}


def _vehicle_capacity_exceeded_map(
    scenario_strategy: str, cost_optimization: CostOptimizationResult
) -> dict[int, bool]:
    cost_summary = next((s for s in cost_optimization.scenarios if s.strategy == scenario_strategy), None)
    if cost_summary is None:
        return {}
    exceeded: dict[int, bool] = {}
    for line in cost_summary.lines:
        if line.vehicle_id is not None:
            exceeded[line.vehicle_id] = exceeded.get(line.vehicle_id, False) or line.vehicle_capacity_exceeded
    return exceeded


def _predict_vehicle_route(
    route: VehicleRoute, business_rules: BusinessRules, vehicle_capacity_exceeded: bool, replanning_triggered: bool
) -> list[StopETA]:
    stop_etas: list[StopETA] = []
    cumulative_hours = 0.0
    max_lead_time_hours = business_rules.max_lead_time_days * 24

    for stop in route.stops:
        cumulative_hours += stop.travel_time_hours
        predicted_eta_hours = cumulative_hours * (1 + business_rules.eta_variance_buffer_pct)

        reasons: list[str] = []
        if predicted_eta_hours > max_lead_time_hours:
            reasons.append("exceeds_max_lead_time")
        if vehicle_capacity_exceeded:
            reasons.append("vehicle_capacity_exceeded")
        if replanning_triggered:
            reasons.append("replanning_triggered")

        stop_etas.append(
            StopETA(
                vehicle_id=route.vehicle_id,
                store_id=stop.store_id,
                sequence=stop.sequence,
                predicted_eta_hours=predicted_eta_hours,
                at_risk=bool(reasons),
                risk_reasons=reasons,
                suggested_contingency=_CONTINGENCY_BY_REASON[reasons[0]] if reasons else None,
            )
        )
    return stop_etas


def _predict_scenario(
    scenario_route: ScenarioRoutePlan,
    business_rules: BusinessRules,
    cost_optimization: CostOptimizationResult,
    replanning_triggered: bool,
) -> ScenarioETAPrediction:
    exceeded_by_vehicle = _vehicle_capacity_exceeded_map(scenario_route.strategy, cost_optimization)

    stop_etas: list[StopETA] = []
    for route in scenario_route.vehicle_routes:
        stop_etas.extend(
            _predict_vehicle_route(
                route, business_rules, exceeded_by_vehicle.get(route.vehicle_id, False), replanning_triggered
            )
        )

    return ScenarioETAPrediction(
        strategy=scenario_route.strategy,
        stop_etas=stop_etas,
        at_risk_count=sum(1 for s in stop_etas if s.at_risk),
    )


async def predict_eta_node(state: PlanningState) -> dict:
    route_planning = state["route_planning"]

    if not route_planning.scenario_routes:
        message = "No routes to predict ETA for - skipped"
        logger.info(message)
        result = ETAPredictionResult(scenario_predictions=[])
        return {"eta_prediction": result, "trace": [message]}

    business_rules = state["master_data"].business_rules
    cost_optimization = state["cost_optimization"]
    replanning_triggered = state.get("replanning_attempts", 0) > 0

    scenario_predictions = [
        _predict_scenario(scenario_route, business_rules, cost_optimization, replanning_triggered)
        for scenario_route in route_planning.scenario_routes
    ]

    total_at_risk = sum(p.at_risk_count for p in scenario_predictions)
    message = f"Predicted ETAs for {len(scenario_predictions)} scenario(s) ({total_at_risk} stop(s) at risk)"
    logger.info(message)

    result = ETAPredictionResult(scenario_predictions=scenario_predictions)
    return {"eta_prediction": result, "trace": [message]}
