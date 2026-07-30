from pydantic import BaseModel, ConfigDict, Field


class StoreBase(BaseModel):
    store_name: str = Field(..., max_length=255)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    capacity: int = Field(..., ge=0)
    priority: int = Field(default=3, ge=1, le=5)


class StoreCreate(StoreBase):
    pass


class StoreRead(StoreBase):
    model_config = ConfigDict(from_attributes=True)

    store_id: int
