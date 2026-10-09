from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity, SoftDeleteEntity, enum_col
from app.utils.dt import utcnow
from app.utils.enums import InspectionResult, InspectionType, ResolutionStatus, Severity


class Inspection(Entity):
    __tablename__ = "inspections"

    batch_id: Mapped[int] = mapped_column(ForeignKey("production_batches.id"), index=True)
    inspection_type: Mapped[InspectionType] = enum_col(InspectionType, index=True)
    inspector_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    material_id: Mapped[int | None] = mapped_column(ForeignKey("materials.id"), nullable=True)
    inspection_date: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    result: Mapped[InspectionResult] = enum_col(InspectionResult, index=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    parameters: Mapped[list["InspectionParameter"]] = relationship(
        back_populates="inspection", cascade="all, delete-orphan", order_by="InspectionParameter.id"
    )


class InspectionParameter(Entity):
    __tablename__ = "inspection_parameters"

    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspections.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    expected_value: Mapped[str] = mapped_column(String(100))
    actual_value: Mapped[str] = mapped_column(String(100))
    tolerance: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    inspection: Mapped[Inspection] = relationship(back_populates="parameters")


class Defect(SoftDeleteEntity):
    __tablename__ = "defects"

    batch_id: Mapped[int] = mapped_column(ForeignKey("production_batches.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    inspection_id: Mapped[int | None] = mapped_column(ForeignKey("inspections.id"), nullable=True)
    defect_type: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[Severity] = enum_col(Severity, index=True)
    quantity_affected: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrective_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_status: Mapped[ResolutionStatus] = enum_col(ResolutionStatus, default=ResolutionStatus.OPEN, index=True)
    reported_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
