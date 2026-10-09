from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity, SoftDeleteEntity, enum_col
from app.models.bom import BOM
from app.models.plant import ProductionLine
from app.models.product import Product
from app.utils.dt import utcnow
from app.utils.enums import ApprovalStage, BatchStatus, OrderPriority, OrderStatus


class ProductionOrder(SoftDeleteEntity):
    __tablename__ = "production_orders"

    order_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    bom_id: Mapped[int | None] = mapped_column(ForeignKey("boms.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer)
    target_date: Mapped[date] = mapped_column(Date, index=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_lines.id"), index=True)
    priority: Mapped[OrderPriority] = enum_col(OrderPriority, default=OrderPriority.MEDIUM, index=True)
    supervisor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    status: Mapped[OrderStatus] = enum_col(OrderStatus, default=OrderStatus.DRAFT, index=True)
    approval_stage: Mapped[ApprovalStage] = enum_col(ApprovalStage, default=ApprovalStage.CREATED, index=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    product: Mapped[Product] = relationship()
    line: Mapped[ProductionLine] = relationship()
    bom: Mapped[BOM | None] = relationship()
    batches: Mapped[list["ProductionBatch"]] = relationship(back_populates="order")

    def _live_batches(self):
        return [b for b in self.batches if b.status != BatchStatus.CANCELLED and not b.is_deleted]

    @property
    def produced_quantity(self) -> int:
        return sum(b.produced_quantity for b in self._live_batches())

    @property
    def rejected_quantity(self) -> int:
        return sum(b.rejected_quantity for b in self._live_batches())

    @property
    def completion_percentage(self) -> float:
        return round(self.produced_quantity / self.quantity * 100, 2) if self.quantity else 0.0


class ProductionBatch(SoftDeleteEntity):
    __tablename__ = "production_batches"

    batch_number: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), index=True)
    planned_quantity: Mapped[int] = mapped_column(Integer)
    produced_quantity: Mapped[int] = mapped_column(Integer, default=0)
    rejected_quantity: Mapped[int] = mapped_column(Integer, default=0)
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_lines.id"), index=True)
    machine_id: Mapped[int | None] = mapped_column(ForeignKey("machines.id"), nullable=True, index=True)
    supervisor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True, index=True)
    status: Mapped[BatchStatus] = enum_col(BatchStatus, default=BatchStatus.PLANNED, index=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    order: Mapped[ProductionOrder] = relationship(back_populates="batches")
    workers: Mapped[list["BatchWorker"]] = relationship(back_populates="batch", cascade="all, delete-orphan")

    # ---- calculated metrics (Level 9) ----
    @property
    def completion_percentage(self) -> float:
        """Good units produced vs planned quantity."""
        return round(self.produced_quantity / self.planned_quantity * 100, 2) if self.planned_quantity else 0.0

    @property
    def rejection_percentage(self) -> float:
        """Rejected units vs total units made (good + rejected)."""
        total = self.produced_quantity + self.rejected_quantity
        return round(self.rejected_quantity / total * 100, 2) if total else 0.0

    @property
    def run_minutes(self) -> float:
        if not self.start_time:
            return 0.0
        return max(((self.end_time or utcnow()) - self.start_time).total_seconds() / 60.0, 0.0)

    @property
    def efficiency(self) -> float:
        """Standard minutes earned by good output / actual run minutes, as a percentage capped at 100.
        (actual run time is floored at 1 minute to avoid division by ~0 for very short runs)."""
        if not self.start_time or not self.produced_quantity:
            return 0.0
        std = self.order.product.standard_production_time or 0
        actual = max(self.run_minutes, 1.0)
        return round(min(self.produced_quantity * std / actual * 100, 100.0), 2)


class BatchWorker(Entity):
    __tablename__ = "batch_workers"
    __table_args__ = (UniqueConstraint("batch_id", "worker_id", name="uq_batch_worker"),)

    batch_id: Mapped[int] = mapped_column(ForeignKey("production_batches.id"), index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True)
    assigned_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    batch: Mapped[ProductionBatch] = relationship(back_populates="workers")


class ProductionOutputLog(Entity):
    """Every output recording; the basis for daily/monthly/shift production figures."""
    __tablename__ = "production_output_logs"

    batch_id: Mapped[int] = mapped_column(ForeignKey("production_batches.id"), index=True)
    produced: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    recorded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True, index=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    batch: Mapped[ProductionBatch] = relationship()
