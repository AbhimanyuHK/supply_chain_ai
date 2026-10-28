"""LLM-native candidate search with independent deterministic feasibility checks.

No mathematical optimization solver is used. The LLM proposes allocations;
Python checks hard stock/demand constraints and scores accepted proposals.
"""
from collections import defaultdict
from functools import lru_cache
from typing import Callable

from pydantic import BaseModel, Field

from app.core.llm import get_chat_model
from app.agents.critic_agent import critique_plan
from app.schemas.allocation import AllocationLine, AllocationScenario
from app.schemas.supply_planning import CandidatePlan


class ProposedLine(BaseModel):
    terminal_id: int
    store_id: int
    product_id: int
    quantity: int = Field(gt=0)


class ProposedPlan(BaseModel):
    lines: list[ProposedLine]
    rationale: str


@lru_cache
def _planner():
    return get_chat_model().with_structured_output(ProposedPlan)


def validate_proposal(proposal: ProposedPlan, shortages, candidate_plans, terminal_stock):
    """Reject invented lanes, negative/overdrawn inventory, and excess deliveries."""
    lanes = {(c.terminal_id, c.store_id, c.product_id): c for c in candidate_plans}
    needs = {(s.store_id, s.product_id): s.shortage_qty for s in shortages}
    outbound = defaultdict(int)
    inbound = defaultdict(int)
    result = []
    for item in proposal.lines:
        key = (item.terminal_id, item.store_id, item.product_id)
        candidate = lanes.get(key)
        if candidate is None or item.quantity <= 0:
            return None
        outbound[(item.terminal_id, item.product_id)] += item.quantity
        inbound[(item.store_id, item.product_id)] += item.quantity
        if outbound[(item.terminal_id, item.product_id)] > terminal_stock.get((item.terminal_id, item.product_id), 0):
            return None
        if inbound[(item.store_id, item.product_id)] > needs.get((item.store_id, item.product_id), 0):
            return None
        result.append(AllocationLine(
            terminal_id=item.terminal_id, store_id=item.store_id,
            product_id=item.product_id, quantity=item.quantity,
            estimated_transport_cost=candidate.estimated_transport_cost,
            estimated_delivery_hours=candidate.estimated_delivery_hours,
        ))
    return result if result else None


def _objective_score(scenario: AllocationScenario, objective: str):
    # Score only validated candidates; lexicographic service/cost ordering.
    if objective == "maximize_service_level":
        return (scenario.fulfillment_rate, -scenario.total_estimated_cost)
    return (scenario.high_priority_shortages_fulfilled, -scenario.total_estimated_cost, scenario.fulfillment_rate)


async def generate_llm_scenarios(
    *, shortages, candidate_plans: list[CandidatePlan], terminal_stock: dict,
    high_priority_store_ids: set[int], summarize: Callable,
    iterations: int, objective: str,
) -> list[AllocationScenario]:
    """Bounded propose-critique-improve loop; retains best valid candidate."""
    if not shortages or not candidate_plans or iterations <= 0:
        return []
    lanes = [
        {"terminal_id": c.terminal_id, "store_id": c.store_id,
         "product_id": c.product_id, "suggested_quantity": c.quantity,
         "estimated_transport_cost": c.estimated_transport_cost}
        for c in candidate_plans
    ]
    demand = [{"store_id": s.store_id, "product_id": s.product_id,
               "shortage_qty": s.shortage_qty, "priority": s.priority}
              for s in shortages]
    best = None
    accepted = []
    feedback = "Generate a diverse initial feasible plan."
    seen = set()
    stagnant = 0
    for iteration in range(iterations):
        prompt = (
            "You are the supply-chain allocation SOLVER, not a ranking assistant. "
            "Produce a COMPLETE proposed allocation using only supplied lanes. "
            "All quantities must be positive integers. Never exceed terminal-product "
            "stock across stores or store-product shortage across terminals. "
            f"Objective: {objective}. Demand: {demand}. "
            f"Stock: {list(terminal_stock.items())}. Lanes: {lanes}. "
            f"Previous feedback: {feedback}. Return structured output."
        )
        proposed = await _planner().ainvoke(prompt)
        lines = validate_proposal(proposed, shortages, candidate_plans, terminal_stock)
        if lines is None:
            feedback = "Your previous allocation violated stock, demand, or lane constraints. Repair it."
            continue
        fingerprint = tuple(sorted((x.terminal_id, x.store_id, x.product_id, x.quantity) for x in lines))
        if fingerprint in seen:
            feedback = "Duplicate candidate: change allocation quantities or sourcing lanes."
            stagnant += 1
            if stagnant >= 2:
                break
            continue
        seen.add(fingerprint)
        scenario = summarize(f"llm_native_{iteration + 1}", lines, shortages, high_priority_store_ids)
        scenario.rationale = proposed.rationale
        accepted.append(scenario)
        if best is None or _objective_score(scenario, objective) > _objective_score(best, objective):
            best = scenario
            stagnant = 0
            feedback = (
                f"Best feasible: fulfillment={best.fulfillment_rate:.4f}, "
                f"estimated_cost={best.total_estimated_cost:.2f}. "
                "Find a different feasible allocation with a better objective."
            )
        else:
            stagnant += 1
            feedback = (
                f"Last proposal did not improve best feasible allocation "
                f"(fulfillment={best.fulfillment_rate:.4f}, cost={best.total_estimated_cost:.2f}). "
                "Try different lanes or quantities."
            )
        if iteration + 1 < iterations:
            try:
                critique = await critique_plan(
                    objective=objective, scenario=scenario, demand=demand,
                    stock=list(terminal_stock.items()), lanes=lanes,
                )
                feedback += (
                    f" Independent critic improvements: {critique.improvements}. "
                    f"Risks: {critique.weaknesses}."
                )
            except Exception:
                # A critic outage must not discard independently validated plans.
                feedback += " Critic unavailable; use the previous objective feedback."
        if stagnant >= 2:
            break
    return accepted
