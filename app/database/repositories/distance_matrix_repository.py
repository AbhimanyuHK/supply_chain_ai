from typing import Sequence

from sqlalchemy import select

from app.database.repositories.base import BaseRepository
from app.models.entities import DistanceMatrix


class DistanceMatrixRepository(BaseRepository[DistanceMatrix]):
    model = DistanceMatrix

    async def list_by_terminal_and_store_ids(
        self, terminal_ids: Sequence[int], store_ids: Sequence[int]
    ) -> Sequence[DistanceMatrix]:
        if not terminal_ids or not store_ids:
            return []

        stmt = select(DistanceMatrix).where(
            DistanceMatrix.terminal_id.in_(terminal_ids),
            DistanceMatrix.store_id.in_(store_ids),
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
