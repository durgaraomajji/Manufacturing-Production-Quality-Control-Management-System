from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity, SoftDeleteEntity, enum_col
from app.utils.enums import ProductStatus


class ProductCategory(Entity):
    __tablename__ = "product_categories"

    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Product(SoftDeleteEntity):
    __tablename__ = "products"

    sku: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("product_categories.id"), nullable=True, index=True)
    unit_of_measure: Mapped[str] = mapped_column(String(20), default="pcs")
    status: Mapped[ProductStatus] = enum_col(ProductStatus, default=ProductStatus.ACTIVE, index=True)
    standard_production_time: Mapped[float] = mapped_column(Float, default=1.0)  # minutes per unit
    stock_quantity: Mapped[float] = mapped_column(Float, default=0)  # finished goods on hand

    category: Mapped[ProductCategory | None] = relationship()
