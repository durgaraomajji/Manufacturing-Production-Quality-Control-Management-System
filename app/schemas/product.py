from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.utils.enums import ProductStatus


class CategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = None


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = None


class CategoryRead(ORMModel):
    id: int
    name: str
    description: str | None


class ProductCreate(BaseModel):
    sku: str = Field(min_length=2, max_length=50, pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    category_id: int | None = None
    unit_of_measure: str = Field(default="pcs", max_length=20)
    status: ProductStatus = ProductStatus.ACTIVE
    standard_production_time: float = Field(default=1.0, gt=0, description="Minutes per unit")


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = None
    category_id: int | None = None
    unit_of_measure: str | None = Field(default=None, max_length=20)
    status: ProductStatus | None = None
    standard_production_time: float | None = Field(default=None, gt=0)


class ProductRead(ORMModel):
    id: int
    sku: str
    name: str
    description: str | None
    category_id: int | None
    unit_of_measure: str
    status: ProductStatus
    standard_production_time: float
    stock_quantity: float
    created_at: datetime
    updated_at: datetime
