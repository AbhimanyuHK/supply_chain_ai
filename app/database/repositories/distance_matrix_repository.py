from typing import Sequence

from sqlalchemy import select

from app.database.repositories.base import BaseRepository, chunked
from app.models.entities import DistanceMatrix

# Two independent `.in_()` lists in one statement - smaller per-dimension chunk
# than the single-list default (500), same reasoning as inventory_repository.py.
_CHUNK_SIZE = 450


class DistanceMatrixRepository(BaseRepository[DistanceMatrix]):
    model = DistanceMatrix

    async def list_by_terminal_and_store_ids(
        self, terminal_ids: Sequence[int], store_ids: Sequence[int]
    ) -> Sequence[DistanceMatrix]:
        if not terminal_ids or not store_ids:
            return []

        rows: list[DistanceMatrix] = []
        for terminal_chunk in chunked(terminal_ids, _CHUNK_SIZE):
            for store_chunk in chunked(store_ids, _CHUNK_SIZE):
                stmt = select(DistanceMatrix).where(
                    DistanceMatrix.terminal_id.in_(terminal_chunk),
                    DistanceMatrix.store_id.in_(store_chunk),
                )
                result = await self.session.execute(stmt)
                rows.extend(result.scalars().all())
        return rows

    async def list_by_store_ids(self, store_ids: Sequence[int]) -> Sequence[DistanceMatrix]:
        """Every distance-matrix row for the given stores, regardless of terminal.

        Used by `MasterDataService` to derive which terminals are actually
        reachable from a scoped set of stores *before* loading their
        inventory/fleet, instead of loading every terminal in the system
        unconditionally (see master_data_service.py).
        """
        if not store_ids:
            return []

        rows: list[DistanceMatrix] = []
        for store_chunk in chunked(store_ids):
            result = await self.session.execute(
                select(DistanceMatrix).where(DistanceMatrix.store_id.in_(store_chunk))
            )
            rows.extend(result.scalars().all())
        return rows
