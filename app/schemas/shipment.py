from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.entities import ShipmentStatus


class ShipmentBase(BaseModel):
    terminal_id: int
    store_id: int
    product_id: int
    quantity: int = Field(..., gt=0)
    shipment_date: date
    status: ShipmentStatus = ShipmentStatus.PLANNED


class ShipmentCreate(ShipmentBase):
    pass


class ShipmentRead(ShipmentBase):
    model_config = ConfigDict(from_attributes=True)

    shipment_id: int
