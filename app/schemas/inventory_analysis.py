from pydantic import BaseModel

from app.models.entities import LocationType


class InventoryAnalysisRecord(BaseModel):
    location_type: LocationType
    location_id: int
    product_id: int

    on_hand_qty: int
    available_qty: int
    reserved_qty: int
    incoming_qty: int
    damaged_qty: int

    # Only computed for store locations, using the Demand Forecast Agent's output
    # as the demand signal — see app/agents/inventory_analysis_agent.py.
    avg_daily_demand: float | None = None
    safety_stock: float | None = None
    reorder_point: float | None = None
    shortage_qty: float = 0.0
    below_reorder_point: bool = False


class InventoryAnalysisResult(BaseModel):
    records: list[InventoryAnalysisRecord]
    # Convenience subset of `records` where shortage_qty > 0, for downstream agents.
    shortages: list[InventoryAnalysisRecord]
