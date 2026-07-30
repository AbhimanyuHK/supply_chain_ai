from pydantic import BaseModel, ConfigDict, Field


class ProductBase(BaseModel):
    sku: str = Field(..., max_length=64)
    name: str = Field(..., max_length=255)
    category: str = Field(..., max_length=128)
    weight: float = Field(..., ge=0)
    volume: float = Field(..., ge=0)
    cost: float = Field(..., ge=0)
    expiry_days: int | None = Field(default=None, ge=0)


class ProductCreate(ProductBase):
    pass


class ProductRead(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
