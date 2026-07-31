import datetime
from collections.abc import Sequence

from sqlalchemy import select

from app.database.repositories.base import BaseRepository, chunked
from app.models.entities import DemandHistory

# Two independent `.in_()` lists in one statement - smaller per-dimension chunk
# than the single-list default (500), same reasoning as inventory_repository.py.
_CHUNK_SIZE = 450


class DemandHistoryRepository(BaseRepository[DemandHistory]):
    model = DemandHistory

    async def list_recent(
        self,
        store_ids: Sequence[int],
        product_ids: Sequence[int],
        since_date: datetime.date,
    ) -> Sequence[DemandHistory]:
        if not store_ids or not product_ids:
            return []

        rows: list[DemandHistory] = []
        for store_chunk in chunked(store_ids, _CHUNK_SIZE):
            for product_chunk in chunked(product_ids, _CHUNK_SIZE):
                stmt = select(DemandHistory).where(
                    DemandHistory.store_id.in_(store_chunk),
                    DemandHistory.product_id.in_(product_chunk),
                    DemandHistory.date >= since_date,
                )
                result = await self.session.execute(stmt)
                rows.extend(result.scalars().all())
        return rows
