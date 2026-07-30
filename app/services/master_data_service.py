"""Orchestrates the repository layer into a single MasterDataSnapshot for a planning run."""

import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.business_rules import get_business_rules
from app.database.repositories import (
    DemandHistoryRepository,
    DistanceMatrixRepository,
    FleetRepository,
    InventoryRepository,
    ProductRepository,
    StoreRepository,
    TerminalRepository,
)
from app.schemas.demand import DemandHistoryRead
from app.schemas.distance import DistanceMatrixRead
from app.schemas.fleet import FleetRead
from app.schemas.inventory import InventoryRead
from app.schemas.planning import MasterDataSnapshot, PlanningRequest
from app.schemas.product import ProductRead
from app.schemas.store import StoreRead
from app.schemas.terminal import TerminalRead


class MasterDataService:
    """Loads a scoped, consistent snapshot of all master data for one planning run.

    "Scoped" matters at the target scale (1,000+ stores, 10,000+ terminals,
    millions of inventory rows): a planning run loads only the stores/products
    the request asks for (or everything, if unset) and only a trailing window
    of demand history, rather than the entire warehouse.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.store_repo = StoreRepository(session)
        self.terminal_repo = TerminalRepository(session)
        self.product_repo = ProductRepository(session)
        self.inventory_repo = InventoryRepository(session)
        self.demand_history_repo = DemandHistoryRepository(session)
        self.fleet_repo = FleetRepository(session)
        self.distance_matrix_repo = DistanceMatrixRepository(session)

    async def load(self, request: PlanningRequest) -> MasterDataSnapshot:
        stores = (
            await self.store_repo.list_by_ids(request.store_ids)
            if request.store_ids
            else await self.store_repo.list_all()
        )
        products = (
            await self.product_repo.list_by_ids(request.product_ids)
            if request.product_ids
            else await self.product_repo.list_all()
        )
        # All terminals are always in scope: any of them could be a supply source
        # for the requested stores, which the Supply Planning Agent decides later.
        terminals = await self.terminal_repo.list_all()

        store_ids = [s.store_id for s in stores]
        terminal_ids = [t.terminal_id for t in terminals]
        product_ids = [p.product_id for p in products]

        inventory = await self.inventory_repo.list_for_locations_and_products(
            terminal_ids=terminal_ids, store_ids=store_ids, product_ids=product_ids
        )

        since_date = request.planning_date - datetime.timedelta(days=request.demand_history_window_days)
        demand_history = await self.demand_history_repo.list_recent(
            store_ids=store_ids, product_ids=product_ids, since_date=since_date
        )

        fleet = await self.fleet_repo.list_by_terminal_ids(terminal_ids)
        distance_matrix = await self.distance_matrix_repo.list_by_terminal_and_store_ids(
            terminal_ids=terminal_ids, store_ids=store_ids
        )

        return MasterDataSnapshot(
            stores=[StoreRead.model_validate(s) for s in stores],
            terminals=[TerminalRead.model_validate(t) for t in terminals],
            products=[ProductRead.model_validate(p) for p in products],
            inventory=[InventoryRead.model_validate(i) for i in inventory],
            demand_history=[DemandHistoryRead.model_validate(d) for d in demand_history],
            fleet=[FleetRead.model_validate(f) for f in fleet],
            distance_matrix=[DistanceMatrixRead.model_validate(dm) for dm in distance_matrix],
            business_rules=get_business_rules(),
            loaded_at=datetime.datetime.now(datetime.timezone.utc),
        )
