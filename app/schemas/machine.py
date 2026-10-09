from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.utils.enums import MachineStatus


class MachineCreate(BaseModel):
    machine_code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=150)
    machine_type: str = Field(min_length=2, max_length=100)
    line_id: int
    installation_date: date | None = None
    status: MachineStatus = MachineStatus.IDLE
    operating_hours: float = Field(default=0, ge=0)
    maintenance_interval_days: int | None = Field(default=None, gt=0, description="Preventive maintenance interval")
    last_maintenance_date: date | None = None
    description: str | None = None


class MachineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    machine_type: str | None = Field(default=None, min_length=2, max_length=100)
    line_id: int | None = None
    installation_date: date | None = None
    maintenance_interval_days: int | None = Field(default=None, gt=0)
    description: str | None = None


class MachineStatusUpdate(BaseModel):
    status: MachineStatus
    reason: str | None = Field(default=None, max_length=500)


class MachineRead(ORMModel):
    id: int
    machine_code: str
    name: str
    machine_type: str
    line_id: int
    installation_date: date | None
    status: MachineStatus
    operating_hours: float
    maintenance_interval_days: int | None
    last_maintenance_date: date | None
    next_maintenance_due: date | None
    description: str | None
    created_at: datetime
    updated_at: datetime
