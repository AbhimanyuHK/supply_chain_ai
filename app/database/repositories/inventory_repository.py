from typing import Sequence

from sqlalchemy import and_, or_, select

from app.database.repositories.base import BaseRepository
from app.models.entities import Inventory, LocationType


class InventoryRepository(BaseRepository[Inventory]):
    model = Inventory

    async def list_for_locations_and_products(
        self,
        terminal_ids: Sequence[int],
        store_ids: Sequence[int],
        product_ids: Sequence[int],
    ) -> Sequence[Inventory]:
        if not product_ids or (not terminal_ids and not store_ids):
            return []

        location_filters = []
        if terminal_ids:
            location_filters.append(
                and_(Inventory.location_type == LocationType.TERMINAL, Inventory.location_id.in_(terminal_ids))
            )
        if store_ids:
            location_filters.append(
                and_(Inventory.location_type == LocationType.STORE, Inventory.location_id.in_(store_ids))
            )

        stmt = select(Inventory).where(or_(*location_filters), Inventory.product_id.in_(product_ids))
        result = await self.session.execute(stmt)
        return result.scalars().all()
