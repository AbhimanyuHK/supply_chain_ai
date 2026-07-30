from pydantic import BaseModel

from app.models.entities import LocationType


class ShipmentPlanLine(BaseModel):
    terminal_id: int
    store_id: int
    product_id: int
    quantity: int
    transportation_cost: float
    handling_cost: float
    holding_cost: float
    delay_penalty: float
    total_cost: float
    estimated_delivery_hours: float
    # Reused from Module 5's per-candidate rationale for this exact (terminal, store,
    # product) - not a fresh LLM call per line.
    explanation: str


class InventoryProjection(BaseModel):
    location_type: LocationType
    location_id: int
    product_id: int
    before_qty: int
    after_qty: int


class AlternativeRecommendation(BaseModel):
    strategy: str
    overall_score: float
    total_cost: float
    fulfillment_rate: float
    high_priority_shortages_fulfilled: int
    high_priority_shortages_total: int
    reason_not_selected: str


class FinalRecommendation(BaseModel):
    selected_strategy: str | None
    shipment_plan: list[ShipmentPlanLine]
    expected_total_cost: float
    expected_service_level: float
    expected_inventory_after_shipment: list[InventoryProjection]
    alternative_recommendations: list[AlternativeRecommendation]

    # From Groq - synthesized from the real metrics above, not invented independently.
    business_explanation: str
    risk_assessment: str
    contingency_actions: list[str]
    confidence_score: float

    fell_back_to_invalid_scenario: bool
    unresolved_shortages_count: int
