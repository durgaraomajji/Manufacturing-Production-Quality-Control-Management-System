from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Entity, enum_col
from app.utils.enums import MovementType


class InventoryTransaction(Entity):
    """Immutable ledger of every stock movement (raw materials and finished goods)."""
    __tablename__ = "inventory_transactions"
    __table_args__ = (Index("ix_inv_material_created", "material_id", "created_at"),)

    movement_type: Mapped[MovementType] = enum_col(MovementType, index=True)
    material_id: Mapped[int | None] = mapped_column(ForeignKey("materials.id"), nullable=True, index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    quantity: Mapped[float] = mapped_column(Float)          # absolute size of the movement
    delta: Mapped[float] = mapped_column(Float)             # signed change applied to the balance
    balance_before: Mapped[float] = mapped_column(Float)
    balance_after: Mapped[float] = mapped_column(Float)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("production_batches.id"), nullable=True, index=True)
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    performed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
