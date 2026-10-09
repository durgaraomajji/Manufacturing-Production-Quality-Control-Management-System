"""Raw-material master data and stock operations (Level 5)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models.bom import BOM, BOMItem
from app.models.inventory import InventoryTransaction
from app.models.material import Material
from app.models.production import ProductionOrder
from app.models.user import User
from app.repositories.material import material_category_repo, material_repo
from app.services import audit_service, inventory_service
from app.utils.enums import MaterialStatus, MovementType


def create_material(db: Session, data: dict, user: User) -> Material:
    if material_repo.exists(db, code=data["code"]):
        raise ConflictError(f"Material code '{data['code']}' already exists")
    if data.get("category_id"):
        material_category_repo.get_or_404(db, data["category_id"])
    initial = data.pop("initial_quantity", 0)
    material = material_repo.create(db, {**data, "available_quantity": 0})
    audit_service.log(db, user_id=user.id, action="material.create", entity="material", entity_id=material.id,
                      new=audit_service.snapshot(material))
    if initial > 0:
        inventory_service.apply_material_movement(
            db, material, MovementType.RECEIPT, initial, user_id=user.id, reference_type="opening_stock", remarks="Opening stock"
        )
    return material


def _require_active(material: Material) -> None:
    if material.status != MaterialStatus.ACTIVE:
        raise BusinessRuleError(f"Material {material.code} is {material.status.value}; stock cannot be moved")


def stock_in(db: Session, material: Material, quantity: float, user: User, reference: str | None, remarks: str | None):
    _require_active(material)
    return inventory_service.apply_material_movement(
        db, material, MovementType.RECEIPT, quantity, user_id=user.id, reference_type=reference or "stock_in", remarks=remarks
    )


def stock_out(db: Session, material: Material, quantity: float, user: User, remarks: str | None):
    _require_active(material)
    return inventory_service.apply_material_movement(
        db, material, MovementType.STOCK_OUT, -quantity, user_id=user.id, reference_type="stock_out", remarks=remarks
    )


def adjust(db: Session, material: Material, new_quantity: float, user: User, reason: str):
    return inventory_service.adjust_to(db, material, new_quantity, user_id=user.id, reason=reason)


def usage_history_stmt(material_id: int):
    return (
        select(InventoryTransaction)
        .where(InventoryTransaction.material_id == material_id,
               InventoryTransaction.movement_type.in_([MovementType.CONSUMPTION, MovementType.STOCK_OUT]))
        .order_by(InventoryTransaction.created_at.desc(), InventoryTransaction.id.desc())
    )


def low_stock(db: Session) -> list[Material]:
    return [m for m in db.scalars(select(Material).where(Material.is_deleted.is_(False))).all() if m.is_low_stock]


def check_availability(db: Session, order: ProductionOrder) -> dict:
    """Compare what the order's BOM needs (per unit x order quantity) against stock on hand."""
    if order.bom_id is None:
        raise BusinessRuleError("Order has no BOM; cannot check material availability")
    bom = db.get(BOM, order.bom_id)
    items = []
    for bi in db.scalars(select(BOMItem).where(BOMItem.bom_id == bom.id)).all():
        material = db.get(Material, bi.material_id)
        if material is None:
            raise NotFoundError("Material", bi.material_id)
        required = round(bi.quantity_per_unit * order.quantity, 3)
        shortage = round(max(required - material.available_quantity, 0), 3)
        items.append({
            "material_id": material.id, "material_code": material.code, "material_name": material.name,
            "required_quantity": required, "available_quantity": material.available_quantity,
            "shortage": shortage, "sufficient": shortage == 0,
        })
    return {"order_id": order.id, "sufficient": all(i["sufficient"] for i in items), "items": items}


def delete_material(db: Session, material: Material, user: User) -> None:
    from sqlalchemy import func

    in_active_bom = db.scalar(
        select(func.count()).select_from(BOMItem).join(BOM, BOM.id == BOMItem.bom_id)
        .where(BOMItem.material_id == material.id, BOM.is_active.is_(True)))
    if in_active_bom:
        raise ConflictError("Material is used by an active BOM; deactivate the BOM first")
    if material.available_quantity > 0:
        raise BusinessRuleError("Material still has stock on hand; adjust it to zero first")
    previous = audit_service.snapshot(material)
    material_repo.soft_delete_obj(db, material)
    audit_service.log(db, user_id=user.id, action="material.delete", entity="material", entity_id=material.id, previous=previous)
