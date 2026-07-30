from pydantic import BaseModel


class ScenarioEvaluation(BaseModel):
    strategy: str

    # All computed from real data - the LLM only ever sees these, never invents them.
    inventory_balance_score: float
    """0-1, higher = stock drawn down evenly across the (terminal, product) pairs
    involved, rather than draining one while barely touching another."""
    total_transportation_distance_km: float
    demand_fulfillment_rate: float
    future_inventory_risk_ratio: float
    """0-1, fraction of involved (terminal, product) pairs left below
    `decision_review_critical_stock_threshold` of their pre-shipment stock."""
    total_cost: float
    high_priority_shortages_fulfilled: int
    high_priority_shortages_total: int

    # From Groq: a holistic judgment weighing all of the above, and why.
    overall_score: float
    rationale: str


class DecisionReviewResult(BaseModel):
    evaluations: list[ScenarioEvaluation]
    selected_strategy: str | None
    selection_rationale: str
    # True if no scenario passed Constraint Validation and this is Module 8's
    # best-effort pick rather than a genuine choice among valid options.
    fell_back_to_invalid_scenario: bool
