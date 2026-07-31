from app.database.repositories.base import BaseRepository
from app.models.entities import Shipment


class ShipmentRepository(BaseRepository[Shipment]):
    model = Shipment

    async def create(self, **fields) -> Shipment:
        """Adds and flushes a new row - does NOT commit (matches every other
        repository in this codebase; the caller owns the transaction)."""
        shipment = Shipment(**fields)
        self.session.add(shipment)
        await self.session.flush()
        return shipment
