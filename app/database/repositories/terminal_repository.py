from typing import Sequence

from app.database.repositories.base import BaseRepository
from app.models.entities import Terminal


class TerminalRepository(BaseRepository[Terminal]):
    model = Terminal

    async def list_by_ids(self, terminal_ids: Sequence[int]) -> Sequence[Terminal]:
        return await self._list_by_column_in(Terminal.terminal_id, terminal_ids)
