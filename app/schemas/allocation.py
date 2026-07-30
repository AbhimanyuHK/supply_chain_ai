from pydantic import BaseModel


class AllocationLine(BaseModel):
    terminal_id: int
    store_id: int
    product_id: int
    quantity: int
    estimated_transport_cost: float
    estimated_delivery_hours: float


class AllocationScenario(BaseModel):
    strategy: str
    lines: list[AllocationLine]
    total_quantity_allocated: int
    total_shortage_quantity: float
    fulfillment_rate: float
    total_estimated_cost: float
    high_priority_shortages_fulfilled: int
    high_priority_shortages_total: int
    # Set by the Groq ranking call; None until then.
    rank: int | None = None
    rationale: str | None = None


class AllocationResult(BaseModel):
    scenarios: list[AllocationScenario]
    # The top-ranked scenario's strategy name, or None if there was nothing to allocate.
    recommended_strategy: str | None = None
