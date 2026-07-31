from collections.abc import Sequence

from app.database.repositories.base import BaseRepository
from app.models.entities import Product


class ProductRepository(BaseRepository[Product]):
    model = Product

    async def list_by_ids(self, product_ids: Sequence[int]) -> Sequence[Product]:
        return await self._list_by_column_in(Product.product_id, product_ids)
