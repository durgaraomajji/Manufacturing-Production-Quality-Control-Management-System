from datetime import time

from sqlalchemy import Boolean, ForeignKey, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Entity, SoftDeleteEntity, enum_col
from app.utils.enums import ShiftName, WorkerStatus


class Shift(Entity):
    __tablename__ = "shifts"

    name: Mapped[ShiftName] = enum_col(ShiftName, unique=True)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    def contains(self, t: time) -> bool:
        """True if time-of-day `t` is inside this shift (handles shifts crossing midnight)."""
        if self.start_time <= self.end_time:
            return self.start_time <= t < self.end_time
        return t >= self.start_time or t < self.end_time


class Worker(SoftDeleteEntity):
    __tablename__ = "workers"

    employee_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    skill: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True, index=True)
    line_id: Mapped[int | None] = mapped_column(ForeignKey("production_lines.id"), nullable=True, index=True)
    status: Mapped[WorkerStatus] = enum_col(WorkerStatus, default=WorkerStatus.ACTIVE, index=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
