"""Cost Optimization Agent — sixth LangGraph node.

Recomputes a detailed, real cost breakdown for each of Module 6's allocation
scenarios — transportation (real fleet vehicle selection, not Modules 5/6's
flat per-km proxy), warehouse handling, inventory holding, and delay
penalties — then recommends whichever scenario has the lowest total real
cost among those that still fully satisfy every high-priority store
shortage.

No Groq call: unlike Supply Planning/Allocation, this step is pure
computation (real fleet/product/business-rules arithmetic) and a
deterministic selection rule (minimum cost subject to a coverage
constraint), not a judgment call — so nothing here is delegated to an LLM.
"""

from loguru import logger

from app.agents.state import PlanningState
from app.core.business_rules import BusinessRules
from app.models.entities import VehicleStatus
from app.schemas.allocation import AllocationLine, AllocationScenario
from app.schemas.cost_optimization import CostedLine, CostOptimizationResult, ScenarioCostSummary
from app.schemas.fleet import FleetRead
from app.schemas.planning import MasterDataSnapshot


def _pick_vehicle(
    fleet: list[FleetRead], terminal_id: int, shipment_weight: float, shipment_volume: float
) -> tuple[FleetRead | None, bool]:
    """Returns (vehicle, capable). `capable` is False if the vehicle (if any) can't
    actually carry the shipment - a best-effort fallback, not a rejection."""
    at_terminal = [f for f in fleet if f.terminal_id == terminal_id and f.status == VehicleStatus.AVAILABLE]
    capable = [
        f for f in at_terminal if float(f.capacity_weight) >= shipment_weight and float(f.capacity_volume) >= shipment_volume
    ]
    if capable:
        return min(capable, key=lambda f: float(f.fixed_cost)), True
    if at_terminal:
        return max(at_terminal, key=lambda f: (float(f.capacity_weight), float(f.capacity_volume))), False
    return None, False


def _cost_line(line: AllocationLine, snapshot: MasterDataSnapshot, business_rules: BusinessRules) -> CostedLine:
    product = next(p for p in snapshot.products if p.product_id == line.product_id)
    distance = next(
        (d for d in snapshot.distance_matrix if d.terminal_id == line.terminal_id and d.store_id == line.store_id),
        None,
    )
    distance_km = float(distance.distance_km) if distance else 0.0
    travel_time_hours = float(distance.travel_time) if distance else 0.0

    shipment_weight = float(product.weight) * line.quantity
    shipment_volume = float(product.volume) * line.quantity

    vehicle, capable = _pick_vehicle(snapshot.fleet, line.terminal_id, shipment_weight, shipment_volume)

    if vehicle is not None:
        transportation_cost = float(vehicle.fixed_cost) + float(vehicle.cost_per_km) * distance_km
        vehicle_id = vehicle.vehicle_id
    else:
        # No fleet at all at this terminal - fall back to the flat proxy rate so a
        # total is still produced rather than left undefined.
        transportation_cost = distance_km * business_rules.estimated_transport_cost_per_km
        vehicle_id = None

    handling_cost = business_rules.warehouse_handling_cost_per_unit * line.quantity
    holding_cost = (
        line.quantity
        * float(product.cost)
        * business_rules.inventory_holding_cost_rate
        * business_rules.default_safety_stock_days
    )

    acceptable_hours = business_rules.default_lead_time_days * 24
    delay_hours = max(0.0, travel_time_hours - acceptable_hours)
    delay_penalty = delay_hours * business_rules.delay_penalty_per_hour

    total_cost = transportation_cost + handling_cost + holding_cost + delay_penalty

    return CostedLine(
        terminal_id=line.terminal_id,
        store_id=line.store_id,
        product_id=line.product_id,
        quantity=line.quantity,
        vehicle_id=vehicle_id,
        transportation_cost=transportation_cost,
        handling_cost=handling_cost,
        holding_cost=holding_cost,
        delay_penalty=delay_penalty,
        total_cost=total_cost,
        vehicle_capacity_exceeded=not capable,
    )


def _summarize_scenario_cost(
    scenario: AllocationScenario, snapshot: MasterDataSnapshot, business_rules: BusinessRules
) -> ScenarioCostSummary:
    costed_lines = [_cost_line(line, snapshot, business_rules) for line in scenario.lines]

    return ScenarioCostSummary(
        strategy=scenario.strategy,
        lines=costed_lines,
        total_transportation_cost=sum(c.transportation_cost for c in costed_lines),
        total_handling_cost=sum(c.handling_cost for c in costed_lines),
        total_holding_cost=sum(c.holding_cost for c in costed_lines),
        total_delay_penalty=sum(c.delay_penalty for c in costed_lines),
        total_cost=sum(c.total_cost for c in costed_lines),
        high_priority_shortages_fulfilled=scenario.high_priority_shortages_fulfilled,
        high_priority_shortages_total=scenario.high_priority_shortages_total,
        fully_satisfies_high_priority=(
            scenario.high_priority_shortages_fulfilled == scenario.high_priority_shortages_total
        ),
        fulfillment_rate=scenario.fulfillment_rate,
    )


def _recommend(
    scenarios: list[ScenarioCostSummary], objective: str = "minimize_cost"
) -> tuple[str | None, str]:
    """Deterministic scenario selection, driven by `PlanningRequest.optimization_objective`.

    'minimize_cost' (default): cheapest scenario among those that fully satisfy
    every high-priority shortage, falling back to best high-priority coverage
    then cost if none fully qualify - unchanged from before this field existed.

    'maximize_service_level': highest fulfillment rate, with cost only as a
    tiebreaker - for when covering more demand matters more than the price tag
    (e.g. a holiday-rush run vs. normal operations).
    """
    if not scenarios:
        return None, "No allocation scenarios to evaluate."

    if objective == "maximize_service_level":
        best = max(scenarios, key=lambda s: (s.fulfillment_rate, -s.total_cost))
        rationale = (
            f"'{best.strategy}' has the highest demand fulfillment rate ({best.fulfillment_rate:.0%}) "
            f"among all scenarios (cost used only as a tiebreaker; total cost {best.total_cost:.2f})."
        )
        return best.strategy, rationale

    fully_satisfying = [s for s in scenarios if s.fully_satisfies_high_priority]
    pool = fully_satisfying if fully_satisfying else scenarios
    best = min(pool, key=lambda s: s.total_cost)

    if fully_satisfying:
        rationale = (
            f"'{best.strategy}' has the lowest total cost ({best.total_cost:.2f}) among scenarios "
            "that fully satisfy every high-priority store shortage."
        )
    else:
        rationale = (
            f"No scenario fully satisfies every high-priority shortage; '{best.strategy}' has the "
            f"lowest total cost ({best.total_cost:.2f}) among the options available "
            f"({best.high_priority_shortages_fulfilled}/{best.high_priority_shortages_total} "
            "high-priority shortages covered)."
        )
    return best.strategy, rationale


async def optimize_cost_node(state: PlanningState) -> dict:
    allocation = state["allocation"]

    if not allocation.scenarios:
        message = "No allocation scenarios to cost - skipped"
        logger.info(message)
        result = CostOptimizationResult(scenarios=[], recommended_strategy=None, recommendation_rationale=message)
        return {"cost_optimization": result, "trace": [message]}

    snapshot = state["master_data"]
    business_rules = snapshot.business_rules

    scenario_costs = [_summarize_scenario_cost(s, snapshot, business_rules) for s in allocation.scenarios]
    recommended_strategy, rationale = _recommend(scenario_costs, state["request"].optimization_objective)

    result = CostOptimizationResult(
        scenarios=scenario_costs, recommended_strategy=recommended_strategy, recommendation_rationale=rationale
    )

    message = f"Costed {len(scenario_costs)} scenarios; recommended: {recommended_strategy} - {rationale}"
    logger.info(message)

    return {"cost_optimization": result, "trace": [message]}
