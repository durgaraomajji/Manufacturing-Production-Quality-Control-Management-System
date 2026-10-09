"""Bill of Materials with versioning (Level 6).

Rules
  * A product can have many BOM versions but only one active version.
  * A BOM that is referenced by a production order is frozen - create a new version instead.
  * Every material must exist and be active; a material appears once per BOM; quantities are > 0.
"""
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models.bom import BOM, BOMItem
from app.models.material import Material
from app.models.production import ProductionOrder
from app.models.user import User
from app.repositories.product import bom_repo, product_repo
from app.services import audit_service
from app.utils.enums import AuditAction, MaterialStatus


def _snap(bom: BOM) -> dict:
    return {
        "version": bom.version, "is_active": bom.is_active,
        "items": [{"material_id": i.material_id, "quantity_per_unit": i.quantity_per_unit} for i in bom.items],
    }


def _validate_materials(db: Session, items: list[dict]) -> None:
    for item in items:
        material = db.get(Material, item["material_id"])
        if material is None or material.is_deleted:
            raise NotFoundError("Material", item["material_id"])
        if material.status != MaterialStatus.ACTIVE:
            raise BusinessRuleError(f"Material {material.code} is {material.status.value} and cannot be used in a BOM")


def is_locked(db: Session, bom: BOM) -> bool:
    return db.scalar(select(func.count()).select_from(ProductionOrder).where(ProductionOrder.bom_id == bom.id)) > 0


def _assert_editable(db: Session, bom: BOM) -> None:
    if is_locked(db, bom):
        raise ConflictError(f"BOM v{bom.version} is used by production orders and is frozen. Create a new version to change it.")


def active_bom_for_product(db: Session, product_id: int) -> BOM | None:
    return db.scalars(select(BOM).where(BOM.product_id == product_id, BOM.is_active.is_(True))).first()


def _deactivate_others(db: Session, bom: BOM) -> None:
    db.execute(update(BOM).where(BOM.product_id == bom.product_id, BOM.id != bom.id).values(is_active=False))


def create_bom(db: Session, data: dict, user: User) -> BOM:
    product = product_repo.get_or_404(db, data["product_id"])
    items = [i if isinstance(i, dict) else i.model_dump() for i in data["items"]]
    _validate_materials(db, items)
    version = (db.scalar(select(func.max(BOM.version)).where(BOM.product_id == product.id)) or 0) + 1
    bom = bom_repo.create(db, {"product_id": product.id, "version": version, "name": data.get("name"), "notes": data.get("notes")})
    for item in items:
        bom.items.append(BOMItem(material_id=item["material_id"], quantity_per_unit=item["quantity_per_unit"]))
    db.flush()
    if data.get("activate"):
        activate(db, bom, user, _audit=False)
    audit_service.log(db, user_id=user.id, action=AuditAction.BOM_CHANGE, entity="bom", entity_id=bom.id, new=_snap(bom))
    return bom


def update_bom(db: Session, bom: BOM, data: dict, user: User) -> BOM:
    _assert_editable(db, bom)
    previous = _snap(bom)
    for field in ("name", "notes"):
        if field in data:
            setattr(bom, field, data[field])
    if data.get("items") is not None:
        items = [i if isinstance(i, dict) else i.model_dump() for i in data["items"]]
        _validate_materials(db, items)
        bom.items.clear()
        db.flush()
        for item in items:
            bom.items.append(BOMItem(material_id=item["material_id"], quantity_per_unit=item["quantity_per_unit"]))
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.BOM_CHANGE, entity="bom", entity_id=bom.id, previous=previous, new=_snap(bom))
    return bom


def add_item(db: Session, bom: BOM, material_id: int, quantity_per_unit: float, user: User) -> BOM:
    _assert_editable(db, bom)
    _validate_materials(db, [{"material_id": material_id}])
    if any(i.material_id == material_id for i in bom.items):
        raise ConflictError("Material is already part of this BOM; update its quantity instead")
    previous = _snap(bom)
    bom.items.append(BOMItem(material_id=material_id, quantity_per_unit=quantity_per_unit))
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.BOM_CHANGE, entity="bom", entity_id=bom.id, previous=previous, new=_snap(bom))
    return bom


def update_item(db: Session, bom: BOM, material_id: int, quantity_per_unit: float, user: User) -> BOM:
    _assert_editable(db, bom)
    item = next((i for i in bom.items if i.material_id == material_id), None)
    if item is None:
        raise NotFoundError("BOM item", material_id)
    previous = _snap(bom)
    item.quantity_per_unit = quantity_per_unit
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.BOM_CHANGE, entity="bom", entity_id=bom.id, previous=previous, new=_snap(bom))
    return bom


def remove_item(db: Session, bom: BOM, material_id: int, user: User) -> BOM:
    _assert_editable(db, bom)
    item = next((i for i in bom.items if i.material_id == material_id), None)
    if item is None:
        raise NotFoundError("BOM item", material_id)
    if len(bom.items) == 1:
        raise BusinessRuleError("A BOM must keep at least one material")
    previous = _snap(bom)
    bom.items.remove(item)
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.BOM_CHANGE, entity="bom", entity_id=bom.id, previous=previous, new=_snap(bom))
    return bom


def new_version(db: Session, bom: BOM, user: User) -> BOM:
    """Copy `bom` into the next (inactive) version so it can be edited safely."""
    version = db.scalar(select(func.max(BOM.version)).where(BOM.product_id == bom.product_id)) + 1
    copy = bom_repo.create(db, {"product_id": bom.product_id, "version": version, "name": bom.name, "notes": bom.notes})
    for item in bom.items:
        copy.items.append(BOMItem(material_id=item.material_id, quantity_per_unit=item.quantity_per_unit))
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.BOM_CHANGE, entity="bom", entity_id=copy.id,
                      previous={"copied_from": bom.id}, new=_snap(copy))
    return copy


def activate(db: Session, bom: BOM, user: User, _audit: bool = True) -> BOM:
    if not bom.items:
        raise BusinessRuleError("Cannot activate an empty BOM")
    _validate_materials(db, [{"material_id": i.material_id} for i in bom.items])
    previous = _snap(bom)
    _deactivate_others(db, bom)
    bom.is_active = True
    db.flush()
    if _audit:
        audit_service.log(db, user_id=user.id, action=AuditAction.BOM_CHANGE, entity="bom", entity_id=bom.id, previous=previous, new=_snap(bom))
    return bom


def deactivate(db: Session, bom: BOM, user: User) -> BOM:
    previous = _snap(bom)
    bom.is_active = False
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.BOM_CHANGE, entity="bom", entity_id=bom.id, previous=previous, new=_snap(bom))
    return bom
