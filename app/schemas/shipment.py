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
    # Populated by the Fleet Assignment Agent (Phase 2) - None if the fleet module
    # is disabled or this line couldn't be assigned a vehicle.
    vehicle_id: int | None = None
    # Which PlanningRun produced this shipment.
    planning_run_id: int | None = None


class ShipmentCreate(ShipmentBase):
    pass


class ShipmentRead(ShipmentBase):
    model_config = ConfigDict(from_attributes=True)

    shipment_id: int
