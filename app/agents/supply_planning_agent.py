"""Supply Planning Agent — fourth LangGraph node, and the first to call an LLM.

For every store shortage from the Inventory Analysis Agent, finds candidate
supplying terminals from real master data (terminal inventory + the distance
matrix), computes real cost/delivery-time estimates for each, and asks the
configured reasoning engine (Groq by default, or a local Ollama model - see
`app/core/llm.py`) to propose several alternative sourcing plans with a
rationale and a score.

Division of labor with the LLM, deliberately narrow: it decides *quantity*,
*rationale*, and *score* for each candidate plan. It never gets to invent
distance, cost, or delivery time — those are computed here from actual data
and simply handed back attached to whichever terminal the LLM picked. This
keeps the numbers trustworthy even though the reasoning is LLM-generated.

Scope boundary, per the spec's own agent breakdown: this agent does not
enforce business/capacity constraints (that's the Constraint Validation
Agent's job, whose job is explicitly to reject invalid plans and send them
back here for replanning) and does not decide cross-store priority
trade-offs (that's the Allocation Agent's job). It only clamps
obviously-impossible quantities (negative, or exceeding a terminal's
available stock).

When the Constraint Validation Agent rejects every scenario and loops back
here (`state["constraint_validation"].replanning_triggered`), this node
folds the specific violation messages for each affected shortage into that
shortage's prompt, so the retry is an actual correction attempt rather than
an identical re-ask.
"""

import math
from functools import lru_cache

from loguru import logger
from pydantic import BaseModel, Field

from app.agents.state import PlanningState
from app.core.config import get_settings
from app.core.llm import get_active_model_name, get_chat_model
from app.models.entities import LocationType
from app.schemas.forecast import StoreProductRef
from app.schemas.supply_planning import CandidatePlan, SupplyPlanningResult


class _LLMCandidate(BaseModel):
    terminal_id: int
    quantity: int = Field(ge=0)
    rationale: str
    score: float = Field(ge=0, le=100)


class _LLMPlanningResponse(BaseModel):
    candidates: list[_LLMCandidate]


@lru_cache
def _get_structured_llm():
    return get_chat_model().with_structured_output(_LLMPlanningResponse)


def _build_prompt(
    store_id: int,
    product_id: int,
    shortage_qty: float,
    store_priority: int,
    candidates: list[dict],
    business_rules,
    prior_violation_messages: list[str] | None = None,
) -> str:
    candidate_lines = "\n".join(
        f"- Terminal {c['terminal_id']}: {c['available_qty']} units available, "
        f"{c['distance_km']:.1f} km away, {c['estimated_delivery_hours']:.1f}h delivery, "
        f"estimated cost {c['estimated_transport_cost']:.2f}"
        for c in candidates
    )
    # Round up, never down to 0: a fractional shortage (e.g. 0.3 units) is still a real
    # shortage, and displaying "0 more units" would (and did, in testing) mislead the LLM
    # into recommending no shipment at all.
    display_shortage_qty = max(1, math.ceil(shortage_qty))

    retry_note = ""
    if prior_violation_messages:
        joined = "; ".join(prior_violation_messages)
        retry_note = (
            f"\n\nIMPORTANT: a previous proposal for this shortage was rejected during "
            f"constraint validation for these reasons: {joined}. Adjust your quantities to "
            "avoid repeating the same issue (e.g. reduce quantity if a limit was exceeded)."
        )

    return (
        f"Store {store_id} needs {display_shortage_qty} more units of product {product_id} "
        f"(currently below its reorder point). Store priority is {store_priority} "
        f"(1 = highest priority).\n\n"
        f"Candidate supplying terminals:\n{candidate_lines}\n\n"
        f"Business rules: minimum shipment quantity is {business_rules.min_shipment_qty}, "
        f"maximum shipment quantity per product is {business_rules.max_shipment_qty_per_product}.\n\n"
        "Propose one alternative candidate plan per candidate terminal listed above "
        "(skip a terminal only if sourcing from it would be unreasonable). For each plan, "
        "choose a quantity (may be less than the full shortage if that terminal alone "
        "shouldn't cover it all, but never exceed that terminal's available units or the "
        "maximum shipment quantity), a short one-sentence rationale, and a 0-100 score "
        "reflecting how well it minimizes shortage, distance, and cost."
        f"{retry_note}"
    )


def _prior_violation_messages_by_shortage(state: PlanningState) -> dict[tuple[int, int], list[str]]:
    """Groups the previous replanning attempt's violation messages by (store_id,
    product_id), so plan_supply_node can tell each affected shortage's prompt
    specifically why its last proposal was rejected."""
    validation = state.get("constraint_validation")
    if validation is None or not validation.replanning_triggered:
        return {}

    by_shortage: dict[tuple[int, int], list[str]] = {}
    for violation in validation.unresolved_violations:
        if violation.store_id is None or violation.product_id is None:
            continue  # not tied to a specific shortage (e.g. a terminal-wide issue).
        by_shortage.setdefault((violation.store_id, violation.product_id), []).append(violation.message)
    return by_shortage


async def plan_supply_node(state: PlanningState) -> dict:
    snapshot = state["master_data"]
    shortages = state["inventory_analysis"].shortages
    settings = get_settings()
    business_rules = snapshot.business_rules

    distance_by_pair = {(d.terminal_id, d.store_id): d for d in snapshot.distance_matrix}
    store_priority_by_id = {s.store_id: s.priority for s in snapshot.stores}
    prior_violations_by_shortage = _prior_violation_messages_by_shortage(state)

    candidate_plans: list[CandidatePlan] = []
    unresolved: list[StoreProductRef] = []

    for shortage in shortages:
        store_id = shortage.location_id
        product_id = shortage.product_id

        candidates: list[dict] = []
        for inv in snapshot.inventory:
            if inv.location_type != LocationType.TERMINAL or inv.product_id != product_id:
                continue
            if inv.available_qty <= 0:
                continue
            distance = distance_by_pair.get((inv.location_id, store_id))
            if distance is None:
                continue
            candidates.append(
                {
                    "terminal_id": inv.location_id,
                    "available_qty": inv.available_qty,
                    "distance_km": float(distance.distance_km),
                    "estimated_delivery_hours": float(distance.travel_time),
                    "estimated_transport_cost": float(distance.distance_km)
                    * business_rules.estimated_transport_cost_per_km,
                }
            )

        if not candidates:
            unresolved.append(StoreProductRef(store_id=store_id, product_id=product_id))
            continue

        candidates.sort(key=lambda c: c["distance_km"])
        candidates = candidates[: settings.supply_planning_max_candidate_terminals]
        candidates_by_terminal = {c["terminal_id"]: c for c in candidates}

        prompt = _build_prompt(
            store_id=store_id,
            product_id=product_id,
            shortage_qty=shortage.shortage_qty,
            store_priority=store_priority_by_id.get(store_id, 3),
            candidates=candidates,
            business_rules=business_rules,
            prior_violation_messages=prior_violations_by_shortage.get((store_id, product_id)),
        )

        structured_llm = _get_structured_llm()
        response: _LLMPlanningResponse = await structured_llm.ainvoke(prompt)

        for llm_candidate in response.candidates:
            candidate = candidates_by_terminal.get(llm_candidate.terminal_id)
            if candidate is None:
                continue  # LLM referenced a terminal outside the candidate set - drop it.

            quantity = max(0, min(llm_candidate.quantity, candidate["available_qty"]))
            candidate_plans.append(
                CandidatePlan(
                    terminal_id=candidate["terminal_id"],
                    store_id=store_id,
                    product_id=product_id,
                    quantity=quantity,
                    estimated_transport_cost=candidate["estimated_transport_cost"],
                    estimated_delivery_hours=candidate["estimated_delivery_hours"],
                    rationale=llm_candidate.rationale,
                    score=llm_candidate.score,
                )
            )

    result = SupplyPlanningResult(candidate_plans=candidate_plans, unresolved_shortages=unresolved)

    message = (
        f"Planned supply for {len(shortages) - len(unresolved)}/{len(shortages)} shortages "
        f"({len(candidate_plans)} candidate plans generated via {get_active_model_name()}, "
        f"{len(unresolved)} unresolved - no candidate terminal)"
    )
    logger.info(message)

    return {"supply_planning": result, "trace": [message]}
