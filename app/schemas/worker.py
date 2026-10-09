from datetime import datetime, time

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.utils.enums import ShiftName, WorkerStatus


class ShiftCreate(BaseModel):
    name: ShiftName
    start_time: time
    end_time: time


class ShiftUpdate(BaseModel):
    start_time: time | None = None
    end_time: time | None = None
    is_active: bool | None = None


class ShiftRead(ORMModel):
    id: int
    name: ShiftName
    start_time: time
    end_time: time
    is_active: bool


class WorkerCreate(BaseModel):
    employee_code: str = Field(min_length=2, max_length=50)
    full_name: str = Field(min_length=2, max_length=150)
    user_id: int | None = None
    skill: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    shift_id: int | None = None
    line_id: int | None = None
    status: WorkerStatus = WorkerStatus.ACTIVE
    phone: str | None = Field(default=None, max_length=30)


class WorkerUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    skill: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    shift_id: int | None = None
    line_id: int | None = None
    status: WorkerStatus | None = None
    phone: str | None = Field(default=None, max_length=30)


class WorkerRead(ORMModel):
    id: int
    employee_code: str
    full_name: str
    user_id: int | None
    skill: str | None
    department: str | None
    shift_id: int | None
    line_id: int | None
    status: WorkerStatus
    phone: str | None
    created_at: datetime
