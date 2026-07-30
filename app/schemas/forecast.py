import datetime

from pydantic import BaseModel


class StoreProductRef(BaseModel):
    store_id: int
    product_id: int


class DemandForecastPoint(BaseModel):
    store_id: int
    product_id: int
    date: datetime.date
    predicted_qty: float
    low_qty: float
    high_qty: float


class DemandForecastResult(BaseModel):
    horizon_days: int
    model_name: str
    forecasts: list[DemandForecastPoint]
    # Store/product pairs with no demand history at all — nothing to forecast from.
    skipped_pairs: list[StoreProductRef]
