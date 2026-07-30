"""Schemas for a single planning run: the request that kicks off the LangGraph
workflow, and the master data snapshot the first node produces for every
downstream agent to share.
"""

import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.business_rules import BusinessRules
from app.schemas.demand import DemandHistoryRead
from app.schemas.distance import DistanceMatrixRead
from app.schemas.fleet import FleetRead
from app.schemas.inventory import InventoryRead
from app.schemas.product import ProductRead
from app.schemas.store import StoreRead
from app.schemas.terminal import TerminalRead


class PlanningRequest(BaseModel):
    """Scopes a planning run — which stores/products to plan for, and over what window."""

    planning_date: datetime.date = Field(default_factory=datetime.date.today)
    store_ids: list[int] | None = Field(
        default=None, description="Stores to plan for; None means all stores."
    )
    product_ids: list[int] | None = Field(
        default=None, description="Products to plan for; None means all products."
    )
    demand_history_window_days: int = Field(
        default=90, ge=1, description="How many days of trailing demand history to load."
    )


class MasterDataSnapshot(BaseModel):
    """Everything the Master Data Agent loads for one planning run."""

    model_config = ConfigDict(from_attributes=True)

    stores: list[StoreRead]
    terminals: list[TerminalRead]
    products: list[ProductRead]
    inventory: list[InventoryRead]
    demand_history: list[DemandHistoryRead]
    fleet: list[FleetRead]
    distance_matrix: list[DistanceMatrixRead]
    business_rules: BusinessRules
    loaded_at: datetime.datetime
