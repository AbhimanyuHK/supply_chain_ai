from typing import Sequence

from app.database.repositories.base import BaseRepository
from app.models.entities import Fleet


class FleetRepository(BaseRepository[Fleet]):
    model = Fleet

    async def list_by_terminal_ids(self, terminal_ids: Sequence[int]) -> Sequence[Fleet]:
        return await self._list_by_column_in(Fleet.terminal_id, terminal_ids)
