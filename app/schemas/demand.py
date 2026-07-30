from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class DemandHistoryBase(BaseModel):
    date: date
    store_id: int
    product_id: int
    sales_qty: int = Field(default=0, ge=0)
    promotion: bool = False
    holiday: bool = False


class DemandHistoryCreate(DemandHistoryBase):
    pass


class DemandHistoryRead(DemandHistoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
