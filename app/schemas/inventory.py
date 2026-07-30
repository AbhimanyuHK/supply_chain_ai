from pydantic import BaseModel, ConfigDict, Field

from app.models.entities import LocationType


class InventoryBase(BaseModel):
    location_type: LocationType
    location_id: int
    product_id: int
    available_qty: int = Field(default=0, ge=0)
    reserved_qty: int = Field(default=0, ge=0)
    incoming_qty: int = Field(default=0, ge=0)
    damaged_qty: int = Field(default=0, ge=0)


class InventoryCreate(InventoryBase):
    pass


class InventoryRead(InventoryBase):
    model_config = ConfigDict(from_attributes=True)

    inventory_id: int
