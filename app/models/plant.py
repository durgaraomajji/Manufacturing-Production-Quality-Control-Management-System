from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import SoftDeleteEntity, enum_col
from app.utils.enums import LineStatus, PlantStatus


class Plant(SoftDeleteEntity):
    __tablename__ = "plants"

    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    status: Mapped[PlantStatus] = enum_col(PlantStatus, default=PlantStatus.ACTIVE, index=True)
    production_capacity: Mapped[float] = mapped_column(Float, default=0)  # units per day
    capacity_unit: Mapped[str] = mapped_column(String(30), default="units/day")
    address_line: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    lines: Mapped[list["ProductionLine"]] = relationship(back_populates="plant")


class ProductionLine(SoftDeleteEntity):
    __tablename__ = "production_lines"

    line_code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), index=True)
    production_capacity: Mapped[float] = mapped_column(Float, default=0)  # units per day
    status: Mapped[LineStatus] = enum_col(LineStatus, default=LineStatus.ACTIVE, index=True)
    supervisor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    plant: Mapped[Plant] = relationship(back_populates="lines")
