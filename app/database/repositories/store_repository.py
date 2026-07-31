from collections.abc import Sequence

from app.database.repositories.base import BaseRepository
from app.models.entities import Store


class StoreRepository(BaseRepository[Store]):
    model = Store

    async def list_by_ids(self, store_ids: Sequence[int]) -> Sequence[Store]:
        return await self._list_by_column_in(Store.store_id, store_ids)
