import datetime
from typing import Sequence

from sqlalchemy import select

from app.database.repositories.base import BaseRepository
from app.models.entities import DemandHistory


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

        stmt = select(DemandHistory).where(
            DemandHistory.store_id.in_(store_ids),
            DemandHistory.product_id.in_(product_ids),
            DemandHistory.date >= since_date,
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
