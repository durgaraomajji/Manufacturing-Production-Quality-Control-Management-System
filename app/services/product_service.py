"""Products and product categories (Level 4)."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.models.product import Product
from app.models.production import ProductionOrder
from app.models.user import User
from app.repositories.product import product_category_repo, product_repo
from app.services import audit_service
from app.utils.enums import AuditAction, OrderStatus


def create_category(db: Session, data: dict, user: User):
    if product_category_repo.exists(db, name=data["name"]):
        raise ConflictError(f"Category '{data['name']}' already exists")
    category = product_category_repo.create(db, data)
    audit_service.log(db, user_id=user.id, action="product_category.create", entity="product_category", entity_id=category.id,
                      new=audit_service.snapshot(category))
    return category


def update_category(db: Session, category, data: dict, user: User):
    if "name" in data and data["name"] != category.name and product_category_repo.exists(db, name=data["name"]):
        raise ConflictError(f"Category '{data['name']}' already exists")
    previous = audit_service.snapshot(category)
    product_category_repo.update(db, category, data)
    audit_service.log(db, user_id=user.id, action="product_category.update", entity="product_category", entity_id=category.id,
                      previous=previous, new=audit_service.snapshot(category))
    return category


def create_product(db: Session, data: dict, user: User) -> Product:
    if db.scalars(select(Product).where(func.lower(Product.sku) == data["sku"].lower())).first():
        raise ConflictError(f"SKU '{data['sku']}' already exists")
    if data.get("category_id") is not None:
        product_category_repo.get_or_404(db, data["category_id"])
    product = product_repo.create(db, data)
    audit_service.log(db, user_id=user.id, action=AuditAction.PRODUCT_CREATE, entity="product", entity_id=product.id,
                      new=audit_service.snapshot(product))
    return product


def update_product(db: Session, product: Product, data: dict, user: User) -> Product:
    if data.get("category_id") is not None:
        product_category_repo.get_or_404(db, data["category_id"])
    previous = audit_service.snapshot(product)
    product_repo.update(db, product, data)
    audit_service.log(db, user_id=user.id, action=AuditAction.PRODUCT_UPDATE, entity="product", entity_id=product.id,
                      previous=previous, new=audit_service.snapshot(product))
    return product


def delete_product(db: Session, product: Product, user: User) -> None:
    open_orders = db.scalar(select(func.count()).select_from(ProductionOrder).where(
        ProductionOrder.product_id == product.id, ProductionOrder.is_deleted.is_(False),
        ProductionOrder.status.in_((OrderStatus.DRAFT, OrderStatus.SCHEDULED, OrderStatus.IN_PROGRESS, OrderStatus.PAUSED))))
    if open_orders:
        raise ConflictError("Product has open production orders")
    previous = audit_service.snapshot(product)
    product_repo.soft_delete_obj(db, product)
    audit_service.log(db, user_id=user.id, action="product.delete", entity="product", entity_id=product.id, previous=previous)
