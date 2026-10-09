from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity


class BOM(Entity):
    """Bill of materials. Several versions can exist per product but only one may be active."""
    __tablename__ = "boms"
    __table_args__ = (UniqueConstraint("product_id", "version", name="uq_bom_product_version"),)

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    items: Mapped[list["BOMItem"]] = relationship(back_populates="bom", cascade="all, delete-orphan", order_by="BOMItem.id")


class BOMItem(Entity):
    __tablename__ = "bom_items"
    __table_args__ = (UniqueConstraint("bom_id", "material_id", name="uq_bom_item_material"),)

    bom_id: Mapped[int] = mapped_column(ForeignKey("boms.id"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), index=True)
    quantity_per_unit: Mapped[float] = mapped_column(Float)

    bom: Mapped[BOM] = relationship(back_populates="items")
