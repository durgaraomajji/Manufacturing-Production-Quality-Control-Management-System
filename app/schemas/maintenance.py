from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, UTCDateTime
from app.utils.enums import DowntimeCategory, MaintenanceStatus, MaintenanceType


class SparePartIn(BaseModel):
    part_name: str = Field(min_length=1, max_length=150)
    part_number: str | None = Field(default=None, max_length=80)
    quantity: float = Field(gt=0)
    unit_cost: float = Field(default=0, ge=0)


class SparePartRead(ORMModel):
    id: int
    part_name: str
    part_number: str | None
    quantity: float
    unit_cost: float


class MaintenanceCreate(BaseModel):
    machine_id: int
    maintenance_type: MaintenanceType
    scheduled_date: date
    technician_id: int | None = None
    description: str | None = None


class MaintenanceUpdate(BaseModel):
    scheduled_date: date | None = None
    technician_id: int | None = None
    description: str | None = None


class MaintenanceComplete(BaseModel):
    labor_cost: float = Field(default=0, ge=0)
    spare_parts: list[SparePartIn] = []
    notes: str | None = None


class MaintenanceRead(ORMModel):
    id: int
    machine_id: int
    maintenance_type: MaintenanceType
    status: MaintenanceStatus
    scheduled_date: date
    started_at: datetime | None
    completed_at: datetime | None
    technician_id: int | None
    description: str | None
    notes: str | None
    labor_cost: float
    parts_cost: float
    total_cost: float
    spare_parts: list[SparePartRead]
    created_at: datetime


class MaintenanceDue(BaseModel):
    machine_id: int
    machine_code: str
    machine_name: str
    due_date: date
    days_until_due: int
    overdue: bool
    source: str  # "schedule" (machine interval) or "record" (scheduled maintenance record)
    maintenance_id: int | None = None


class DowntimeCreate(BaseModel):
    machine_id: int
    category: DowntimeCategory
    reason: str | None = None
    start_time: UTCDateTime
    end_time: UTCDateTime | None = None
    responsible_user_id: int | None = None


class DowntimeClose(BaseModel):
    end_time: UTCDateTime | None = None


class DowntimeRead(ORMModel):
    id: int
    machine_id: int
    line_id: int | None
    category: DowntimeCategory
    reason: str | None
    start_time: datetime
    end_time: datetime | None
    duration_minutes: float | None
    responsible_user_id: int | None
    maintenance_id: int | None


class DowntimePercentage(BaseModel):
    machine_id: int
    window_start: datetime
    window_end: datetime
    window_minutes: float
    downtime_minutes: float
    downtime_percentage: float
