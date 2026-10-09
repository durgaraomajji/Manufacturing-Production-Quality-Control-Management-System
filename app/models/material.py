from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Entity, SoftDeleteEntity, enum_col
from app.utils.enums import MaterialStatus


class MaterialCategory(Entity):
    __tablename__ = "material_categories"

    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Material(SoftDeleteEntity):
    __tablename__ = "materials"

    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("material_categories.id"), nullable=True, index=True)
    unit: Mapped[str] = mapped_column(String(20), default="kg")
    available_quantity: Mapped[float] = mapped_column(Float, default=0)
    minimum_stock_level: Mapped[float] = mapped_column(Float, default=0)
    reorder_level: Mapped[float] = mapped_column(Float, default=0)
    supplier_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    status: Mapped[MaterialStatus] = enum_col(MaterialStatus, default=MaterialStatus.ACTIVE, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def is_low_stock(self) -> bool:
        return self.available_quantity <= max(self.minimum_stock_level, self.reorder_level) and (
            self.minimum_stock_level > 0 or self.reorder_level > 0
        )
