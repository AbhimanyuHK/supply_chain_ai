from collections.abc import Sequence

from sqlalchemy import select

from app.database.repositories.base import BaseRepository, chunked
from app.models.entities import Inventory, LocationType

# This query binds up to 3 independent `.in_()` lists (terminal/store/product ids)
# in one statement, so each needs a smaller chunk than the single-list default
# (500) to keep the combined bound-parameter count well under SQLite's ~999 cap.
_CHUNK_SIZE = 300


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

        # Terminal and store rows are queried separately (not OR'd together) so
        # that chunking each location dimension independently can't produce
        # duplicate rows - location_type already partitions them.
        rows: list[Inventory] = []
        for product_chunk in chunked(product_ids, _CHUNK_SIZE):
            if terminal_ids:
                for terminal_chunk in chunked(terminal_ids, _CHUNK_SIZE):
                    stmt = select(Inventory).where(
                        Inventory.location_type == LocationType.TERMINAL,
                        Inventory.location_id.in_(terminal_chunk),
                        Inventory.product_id.in_(product_chunk),
                    )
                    result = await self.session.execute(stmt)
                    rows.extend(result.scalars().all())
            if store_ids:
                for store_chunk in chunked(store_ids, _CHUNK_SIZE):
                    stmt = select(Inventory).where(
                        Inventory.location_type == LocationType.STORE,
                        Inventory.location_id.in_(store_chunk),
                        Inventory.product_id.in_(product_chunk),
                    )
                    result = await self.session.execute(stmt)
                    rows.extend(result.scalars().all())
        return rows
