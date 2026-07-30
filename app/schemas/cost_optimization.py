from pydantic import BaseModel


class CostedLine(BaseModel):
    terminal_id: int
    store_id: int
    product_id: int
    quantity: int
    # None if no fleet exists at all at this terminal (falls back to the flat proxy rate).
    vehicle_id: int | None
    transportation_cost: float
    handling_cost: float
    holding_cost: float
    delay_penalty: float
    total_cost: float
    # True if no available vehicle at the terminal could carry the full shipment
    # weight/volume (best-effort fallback to the largest available vehicle, or to
    # the flat proxy rate if there's no fleet at all) - informational only; the
    # future Constraint Validation Agent is what actually rejects infeasible plans.
    vehicle_capacity_exceeded: bool


class ScenarioCostSummary(BaseModel):
    strategy: str
    lines: list[CostedLine]
    total_transportation_cost: float
    total_handling_cost: float
    total_holding_cost: float
    total_delay_penalty: float
    total_cost: float
    high_priority_shortages_fulfilled: int
    high_priority_shortages_total: int
    fully_satisfies_high_priority: bool


class CostOptimizationResult(BaseModel):
    scenarios: list[ScenarioCostSummary]
    recommended_strategy: str | None
    # Deterministic, code-generated (not LLM) explanation of the recommendation rule.
    recommendation_rationale: str
