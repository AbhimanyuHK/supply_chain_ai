from pydantic import BaseModel, ConfigDict, Field


class DistanceMatrixBase(BaseModel):
    terminal_id: int
    store_id: int
    distance_km: float = Field(..., ge=0)
    travel_time: float = Field(..., ge=0)


class DistanceMatrixCreate(DistanceMatrixBase):
    pass


class DistanceMatrixRead(DistanceMatrixBase):
    model_config = ConfigDict(from_attributes=True)
