from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SoftDeleteEntity, enum_col
from app.utils.enums import MachineStatus


class Machine(SoftDeleteEntity):
    __tablename__ = "machines"

    machine_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    machine_type: Mapped[str] = mapped_column(String(100), index=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_lines.id"), index=True)
    installation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[MachineStatus] = enum_col(MachineStatus, default=MachineStatus.IDLE, index=True)
    operating_hours: Mapped[float] = mapped_column(Float, default=0)
    maintenance_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_maintenance_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_maintenance_due: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
