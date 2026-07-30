"""Schemas for a single planning run: the request that kicks off the LangGraph
workflow, and the master data snapshot the first node produces for every
downstream agent to share.
"""

import datetime
import hashlib
import json
from typing import Literal

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
    optimization_objective: Literal["minimize_cost", "maximize_service_level"] = Field(
        default="minimize_cost",
        description=(
            "Which goal drives scenario selection in Cost Optimization/Decision Review: "
            "'minimize_cost' (default - cheapest scenario that still fully covers every "
            "high-priority shortage) or 'maximize_service_level' (highest fulfillment "
            "rate, cost as a tiebreaker). A per-run choice, not a global policy - "
            "different runs may legitimately want different trade-offs (e.g. holiday "
            "rush vs. normal operations)."
        ),
    )

    def scope_key(self) -> str:
        """Deterministic fingerprint of this request's scope, for exact-match
        "has this already been run?" lookups against `PlanningRun.scope_key`.

        Store/product ids are sorted first so the same scope always hashes the
        same way regardless of selection order. `planning_date` is included -
        the Demand Forecast Agent's horizon depends on it, so a run from a
        different calendar day genuinely isn't "the same scope" for reuse.
        `optimization_objective` is included too - a different objective is a
        genuinely different desired plan, not a cache-equivalent request.
        """
        canonical = json.dumps(
            {
                "store_ids": sorted(self.store_ids) if self.store_ids else None,
                "product_ids": sorted(self.product_ids) if self.product_ids else None,
                "demand_history_window_days": self.demand_history_window_days,
                "planning_date": self.planning_date.isoformat(),
                "optimization_objective": self.optimization_objective,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
