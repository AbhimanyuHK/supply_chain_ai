from pydantic import BaseModel, ConfigDict, Field

from app.models.entities import VehicleStatus


class FleetBase(BaseModel):
    terminal_id: int
    vehicle_type: str = Field(..., max_length=64)
    capacity_weight: float = Field(..., ge=0)
    capacity_volume: float = Field(..., ge=0)
    cost_per_km: float = Field(..., ge=0)
    fixed_cost: float = Field(..., ge=0)
    status: VehicleStatus = VehicleStatus.AVAILABLE


class FleetCreate(FleetBase):
    pass


class FleetRead(FleetBase):
    model_config = ConfigDict(from_attributes=True)

    vehicle_id: int
