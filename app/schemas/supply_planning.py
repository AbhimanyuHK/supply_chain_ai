from pydantic import BaseModel

from app.schemas.forecast import StoreProductRef


class CandidatePlan(BaseModel):
    """One alternative sourcing option for a single shortage.

    `terminal_id`/`store_id`/`product_id`/`quantity`/`estimated_transport_cost`/
    `estimated_delivery_hours` are all computed from real master data (distance
    matrix, business rules) — the LLM only decides `quantity`, `rationale`, and
    `score`; it never gets to invent the cost/distance/delivery numbers.
    """

    terminal_id: int
    store_id: int
    product_id: int
    quantity: int
    estimated_transport_cost: float
    estimated_delivery_hours: float
    rationale: str
    score: float


class SupplyPlanningResult(BaseModel):
    candidate_plans: list[CandidatePlan]
    # Shortages with no candidate terminal (no stock anywhere, or no distance data)
    # — nothing to propose a plan from.
    unresolved_shortages: list[StoreProductRef]
