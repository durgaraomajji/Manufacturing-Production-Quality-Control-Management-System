from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity, enum_col
from app.utils.enums import DowntimeCategory, MaintenanceStatus, MaintenanceType


class MaintenanceRecord(Entity):
    __tablename__ = "maintenance_records"

    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    maintenance_type: Mapped[MaintenanceType] = enum_col(MaintenanceType, index=True)
    status: Mapped[MaintenanceStatus] = enum_col(MaintenanceStatus, default=MaintenanceStatus.SCHEDULED, index=True)
    scheduled_date: Mapped[date] = mapped_column(Date, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    technician_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    labor_cost: Mapped[float] = mapped_column(Float, default=0)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    spare_parts: Mapped[list["SparePartUsage"]] = relationship(back_populates="maintenance", cascade="all, delete-orphan")

    @property
    def parts_cost(self) -> float:
        return round(sum(p.quantity * p.unit_cost for p in self.spare_parts), 2)

    @property
    def total_cost(self) -> float:
        return round((self.labor_cost or 0) + self.parts_cost, 2)


class SparePartUsage(Entity):
    __tablename__ = "spare_part_usages"

    maintenance_id: Mapped[int] = mapped_column(ForeignKey("maintenance_records.id"), index=True)
    part_name: Mapped[str] = mapped_column(String(150))
    part_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    quantity: Mapped[float] = mapped_column(Float)
    unit_cost: Mapped[float] = mapped_column(Float, default=0)

    maintenance: Mapped[MaintenanceRecord] = relationship(back_populates="spare_parts")


class Downtime(Entity):
    __tablename__ = "downtimes"
    __table_args__ = (Index("ix_downtime_machine_start", "machine_id", "start_time"),)

    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    line_id: Mapped[int | None] = mapped_column(ForeignKey("production_lines.id"), nullable=True, index=True)
    category: Mapped[DowntimeCategory] = enum_col(DowntimeCategory, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    maintenance_id: Mapped[int | None] = mapped_column(ForeignKey("maintenance_records.id"), nullable=True)
