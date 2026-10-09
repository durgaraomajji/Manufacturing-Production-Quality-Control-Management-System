from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.utils.enums import MaterialStatus, MovementType


class MaterialCategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = None


class MaterialCategoryRead(ORMModel):
    id: int
    name: str
    description: str | None


class MaterialCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=200)
    category_id: int | None = None
    unit: str = Field(default="kg", max_length=20)
    initial_quantity: float = Field(default=0, ge=0, description="Opening stock (booked as a receipt)")
    minimum_stock_level: float = Field(default=0, ge=0)
    reorder_level: float = Field(default=0, ge=0)
    supplier_reference: str | None = Field(default=None, max_length=150)
    status: MaterialStatus = MaterialStatus.ACTIVE
    description: str | None = None


class MaterialUpdate(BaseModel):
    """Quantity cannot be edited here - use stock-in / stock-out / adjust so a transaction is recorded."""
    name: str | None = Field(default=None, min_length=2, max_length=200)
    category_id: int | None = None
    unit: str | None = Field(default=None, max_length=20)
    minimum_stock_level: float | None = Field(default=None, ge=0)
    reorder_level: float | None = Field(default=None, ge=0)
    supplier_reference: str | None = Field(default=None, max_length=150)
    status: MaterialStatus | None = None
    description: str | None = None


class MaterialRead(ORMModel):
    id: int
    code: str
    name: str
    category_id: int | None
    unit: str
    available_quantity: float
    minimum_stock_level: float
    reorder_level: float
    supplier_reference: str | None
    status: MaterialStatus
    description: str | None
    is_low_stock: bool
    created_at: datetime
    updated_at: datetime


class StockIn(BaseModel):
    quantity: float = Field(gt=0)
    reference: str | None = Field(default=None, max_length=100, description="PO / delivery note number")
    remarks: str | None = None


class StockOut(BaseModel):
    quantity: float = Field(gt=0)
    remarks: str | None = None


class StockAdjust(BaseModel):
    new_quantity: float = Field(ge=0, description="Counted quantity; the delta is derived")
    reason: str = Field(min_length=3, max_length=500)


class TransactionRead(ORMModel):
    id: int
    movement_type: MovementType
    material_id: int | None
    product_id: int | None
    quantity: float
    delta: float
    balance_before: float
    balance_after: float
    batch_id: int | None
    reference_type: str | None
    reference_id: int | None
    remarks: str | None
    performed_by_id: int | None
    created_at: datetime


class ProductStockAdjust(BaseModel):
    new_quantity: float = Field(ge=0)
    reason: str = Field(min_length=3, max_length=500)
