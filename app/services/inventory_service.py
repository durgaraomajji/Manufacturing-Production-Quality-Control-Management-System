"""Single entry point for every stock change (Levels 5, 16, 20).

All movements go through `apply_material_movement` / `apply_product_movement`, which
  * refuse to drive a balance negative,
  * write an immutable InventoryTransaction (balance before/after),
  * write an audit log entry,
  * raise a low-stock notification when a material crosses its threshold.
Callers own the transaction (commit); an exception anywhere rolls the whole request back.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, InsufficientStockError
from app.models.inventory import InventoryTransaction
from app.models.material import Material
from app.models.product import Product
from app.services import audit_service, notification_service
from app.utils.dt import day_start, utcnow
from app.utils.enums import AuditAction, MovementType, NotificationType

PRECISION = 3


def _r(value: float) -> float:
    return round(value, PRECISION)


def _audit_action(movement_type: MovementType) -> AuditAction:
    return AuditAction.INVENTORY_ADJUSTMENT if movement_type == MovementType.ADJUSTMENT else AuditAction.MATERIAL_MOVEMENT


def apply_material_movement(
    db: Session,
    material: Material,
    movement_type: MovementType,
    delta: float,
    *,
    user_id: int | None,
    batch_id: int | None = None,
    reference_type: str | None = None,
    reference_id: int | None = None,
    remarks: str | None = None,
) -> InventoryTransaction:
    # lock the row so two concurrent movements cannot both pass the balance check (no-op on SQLite)
    material = db.scalars(select(Material).where(Material.id == material.id).with_for_update()).one()
    before = _r(material.available_quantity)
    after = _r(before + delta)
    if after < 0:
        raise InsufficientStockError(
            f"Insufficient stock for {material.code}: available {before} {material.unit}, requested {_r(abs(delta))}",
            details={"material_id": material.id, "available": before, "requested": _r(abs(delta))},
        )
    material.available_quantity = after
    txn = InventoryTransaction(
        movement_type=movement_type, material_id=material.id, quantity=_r(abs(delta)), delta=_r(delta),
        balance_before=before, balance_after=after, batch_id=batch_id, reference_type=reference_type,
        reference_id=reference_id, remarks=remarks, performed_by_id=user_id,
    )
    db.add(txn)
    db.flush()
    audit_service.log(
        db, user_id=user_id, action=_audit_action(movement_type), entity="material", entity_id=material.id,
        previous={"available_quantity": before}, new={"available_quantity": after, "movement": movement_type.value, "delta": _r(delta)},
    )
    if delta < 0 and material.is_low_stock:
        notification_service.notify(
            db, NotificationType.LOW_STOCK, f"Low stock: {material.code}",
            f"{material.name} is down to {after} {material.unit} (minimum {material.minimum_stock_level}, reorder at {material.reorder_level}).",
            severity="warning", entity_type="material", entity_id=material.id, dedupe_key=f"low_stock:{material.id}",
        )
    return txn


def apply_product_movement(
    db: Session,
    product: Product,
    movement_type: MovementType,
    delta: float,
    *,
    user_id: int | None,
    batch_id: int | None = None,
    reference_type: str | None = None,
    reference_id: int | None = None,
    remarks: str | None = None,
    quantity: float | None = None,
) -> InventoryTransaction:
    """Finished-goods movement. REJECTED_GOODS is logged with delta 0 (rejects never enter stock)."""
    product = db.scalars(select(Product).where(Product.id == product.id).with_for_update()).one()
    before = _r(product.stock_quantity)
    after = _r(before + delta)
    if after < 0:
        raise InsufficientStockError(
            f"Insufficient finished goods for {product.sku}: on hand {before}, requested {_r(abs(delta))}",
            details={"product_id": product.id, "available": before, "requested": _r(abs(delta))},
        )
    product.stock_quantity = after
    txn = InventoryTransaction(
        movement_type=movement_type, product_id=product.id,
        quantity=_r(quantity if quantity is not None else abs(delta)), delta=_r(delta),
        balance_before=before, balance_after=after, batch_id=batch_id, reference_type=reference_type,
        reference_id=reference_id, remarks=remarks, performed_by_id=user_id,
    )
    db.add(txn)
    db.flush()
    audit_service.log(
        db, user_id=user_id, action=_audit_action(movement_type), entity="product", entity_id=product.id,
        previous={"stock_quantity": before}, new={"stock_quantity": after, "movement": movement_type.value, "delta": _r(delta)},
    )
    return txn


def adjust_to(db: Session, target, new_quantity: float, *, user_id: int | None, reason: str) -> InventoryTransaction:
    """Stock correction to an absolute counted quantity (material or product)."""
    is_material = isinstance(target, Material)
    current = target.available_quantity if is_material else target.stock_quantity
    delta = _r(new_quantity - current)
    if delta == 0:
        raise BusinessRuleError("Adjustment has no effect: counted quantity equals the current balance")
    fn = apply_material_movement if is_material else apply_product_movement
    return fn(db, target, MovementType.ADJUSTMENT, delta, user_id=user_id, reference_type="adjustment", remarks=reason)


def summary(db: Session) -> dict:
    materials = db.scalars(select(Material).where(Material.is_deleted.is_(False))).all()
    finished = db.scalar(select(func.coalesce(func.sum(Product.stock_quantity), 0)).where(Product.is_deleted.is_(False)))
    today_txns = db.scalar(
        select(func.count()).select_from(InventoryTransaction).where(InventoryTransaction.created_at >= day_start(utcnow().date()))
    )
    return {
        "total_materials": len(materials),
        "low_stock_materials": sum(1 for m in materials if m.is_low_stock),
        "out_of_stock_materials": sum(1 for m in materials if m.available_quantity <= 0),
        "total_finished_goods_units": _r(finished or 0),
        "transactions_today": today_txns or 0,
    }
