from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.utils.enums import LineStatus, PlantStatus


class PlantCreate(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    name: str = Field(min_length=2, max_length=150)
    status: PlantStatus = PlantStatus.ACTIVE
    production_capacity: float = Field(default=0, ge=0, description="Units per day")
    capacity_unit: str = "units/day"
    address_line: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    description: str | None = None
    manager_id: int | None = None


class PlantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    production_capacity: float | None = Field(default=None, ge=0)
    capacity_unit: str | None = None
    address_line: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    description: str | None = None


class PlantStatusUpdate(BaseModel):
    status: PlantStatus
    reason: str | None = Field(default=None, max_length=500)


class PlantManagerAssign(BaseModel):
    manager_id: int


class PlantRead(ORMModel):
    id: int
    code: str
    name: str
    status: PlantStatus
    production_capacity: float
    capacity_unit: str
    address_line: str | None
    city: str | None
    state: str | None
    country: str | None
    postal_code: str | None
    description: str | None
    manager_id: int | None
    created_at: datetime
    updated_at: datetime


class LineCreate(BaseModel):
    line_code: str = Field(min_length=2, max_length=30)
    name: str = Field(min_length=2, max_length=150)
    plant_id: int
    production_capacity: float = Field(default=0, ge=0, description="Units per day")
    status: LineStatus = LineStatus.ACTIVE
    supervisor_id: int | None = None
    description: str | None = None


class LineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    production_capacity: float | None = Field(default=None, ge=0)
    status: LineStatus | None = None
    supervisor_id: int | None = None
    description: str | None = None


class LineRead(ORMModel):
    id: int
    line_code: str
    name: str
    plant_id: int
    production_capacity: float
    status: LineStatus
    supervisor_id: int | None
    description: str | None
    created_at: datetime
    updated_at: datetime
