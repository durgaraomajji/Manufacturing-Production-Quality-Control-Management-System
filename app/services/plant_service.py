"""Plants and production lines (Levels 2 and 3)."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models.machine import Machine
from app.models.plant import Plant, ProductionLine
from app.models.production import ProductionOrder
from app.models.user import User
from app.repositories.plant import line_repo, plant_repo
from app.repositories.user import user_repo
from app.services import audit_service
from app.utils.enums import AuditAction, LineStatus, MachineStatus, OrderStatus, PlantStatus, Role

_OPEN_ORDER_STATES = (OrderStatus.SCHEDULED, OrderStatus.IN_PROGRESS, OrderStatus.PAUSED)


def _validate_user_role(db: Session, user_id: int | None, allowed: set[Role], label: str) -> None:
    if user_id is None:
        return
    target = user_repo.get(db, user_id)
    if target is None:
        raise NotFoundError(label, user_id)
    if target.role not in allowed or not target.is_active:
        raise BusinessRuleError(f"{label} must be an active user with role: {', '.join(sorted(r.value for r in allowed))}")


def _orders_in_production(db: Session, *, plant_id: int | None = None, line_id: int | None = None) -> int:
    stmt = select(func.count()).select_from(ProductionOrder).where(
        ProductionOrder.is_deleted.is_(False), ProductionOrder.status.in_((OrderStatus.IN_PROGRESS, OrderStatus.PAUSED)))
    if line_id is not None:
        stmt = stmt.where(ProductionOrder.line_id == line_id)
    if plant_id is not None:
        stmt = stmt.join(ProductionLine, ProductionLine.id == ProductionOrder.line_id).where(ProductionLine.plant_id == plant_id)
    return db.scalar(stmt) or 0


# ---------------------------------------------------------------- plants
def create_plant(db: Session, data: dict, user: User) -> Plant:
    if plant_repo.exists(db, code=data["code"]):
        raise ConflictError(f"Plant code '{data['code']}' already exists")
    _validate_user_role(db, data.get("manager_id"), {Role.PLANT_MANAGER}, "Plant manager")
    plant = plant_repo.create(db, data)
    audit_service.log(db, user_id=user.id, action=AuditAction.PLANT_CREATE, entity="plant", entity_id=plant.id,
                      new=audit_service.snapshot(plant))
    return plant


def update_plant(db: Session, plant: Plant, data: dict, user: User) -> Plant:
    previous = audit_service.snapshot(plant)
    plant_repo.update(db, plant, data)
    audit_service.log(db, user_id=user.id, action=AuditAction.PLANT_UPDATE, entity="plant", entity_id=plant.id,
                      previous=previous, new=audit_service.snapshot(plant))
    return plant


def change_status(db: Session, plant: Plant, status: PlantStatus, reason: str | None, user: User) -> Plant:
    if status == plant.status:
        return plant
    if status != PlantStatus.ACTIVE and _orders_in_production(db, plant_id=plant.id):
        raise BusinessRuleError("Plant has production orders in progress; pause or complete them first")
    previous = {"status": plant.status.value}
    plant.status = status
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.PLANT_UPDATE, entity="plant", entity_id=plant.id,
                      previous=previous, new={"status": status.value, "reason": reason})
    return plant


def assign_manager(db: Session, plant: Plant, manager_id: int, user: User) -> Plant:
    _validate_user_role(db, manager_id, {Role.PLANT_MANAGER}, "Plant manager")
    previous = {"manager_id": plant.manager_id}
    plant.manager_id = manager_id
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.PLANT_UPDATE, entity="plant", entity_id=plant.id,
                      previous=previous, new={"manager_id": manager_id})
    return plant


def delete_plant(db: Session, plant: Plant, user: User) -> None:
    if db.scalar(select(func.count()).select_from(ProductionLine).where(
            ProductionLine.plant_id == plant.id, ProductionLine.is_deleted.is_(False))):
        raise ConflictError("Plant still has production lines; delete or move them first")
    previous = audit_service.snapshot(plant)
    plant_repo.soft_delete_obj(db, plant)
    audit_service.log(db, user_id=user.id, action="plant.delete", entity="plant", entity_id=plant.id, previous=previous)


# ---------------------------------------------------------------- production lines
def create_line(db: Session, data: dict, user: User) -> ProductionLine:
    plant = plant_repo.get_or_404(db, data["plant_id"])
    if plant.status == PlantStatus.INACTIVE:
        raise BusinessRuleError("Cannot add a production line to an inactive plant")
    if line_repo.exists(db, line_code=data["line_code"]):
        raise ConflictError(f"Line code '{data['line_code']}' already exists")
    _validate_user_role(db, data.get("supervisor_id"), {Role.PRODUCTION_SUPERVISOR}, "Supervisor")
    if plant.production_capacity and data.get("production_capacity", 0) > plant.production_capacity:
        raise BusinessRuleError("Line capacity cannot exceed the plant's production capacity")
    line = line_repo.create(db, data)
    audit_service.log(db, user_id=user.id, action=AuditAction.LINE_CREATE, entity="production_line", entity_id=line.id,
                      new=audit_service.snapshot(line))
    return line


def update_line(db: Session, line: ProductionLine, data: dict, user: User) -> ProductionLine:
    if "supervisor_id" in data:
        _validate_user_role(db, data["supervisor_id"], {Role.PRODUCTION_SUPERVISOR}, "Supervisor")
    if data.get("status") not in (None, LineStatus.ACTIVE) and _orders_in_production(db, line_id=line.id):
        raise BusinessRuleError("Line has production orders in progress; pause or complete them first")
    plant = plant_repo.get_or_404(db, line.plant_id)
    if plant.production_capacity and data.get("production_capacity", 0) > plant.production_capacity:
        raise BusinessRuleError("Line capacity cannot exceed the plant's production capacity")
    previous = audit_service.snapshot(line)
    line_repo.update(db, line, data)
    audit_service.log(db, user_id=user.id, action=AuditAction.LINE_UPDATE, entity="production_line", entity_id=line.id,
                      previous=previous, new=audit_service.snapshot(line))
    return line


def delete_line(db: Session, line: ProductionLine, user: User) -> None:
    if db.scalar(select(func.count()).select_from(Machine).where(
            Machine.line_id == line.id, Machine.is_deleted.is_(False), Machine.status != MachineStatus.DECOMMISSIONED)):
        raise ConflictError("Line still has machines; decommission or move them first")
    if db.scalar(select(func.count()).select_from(ProductionOrder).where(
            ProductionOrder.line_id == line.id, ProductionOrder.is_deleted.is_(False),
            ProductionOrder.status.in_((OrderStatus.DRAFT,) + _OPEN_ORDER_STATES))):
        raise ConflictError("Line has open production orders")
    previous = audit_service.snapshot(line)
    line_repo.soft_delete_obj(db, line)
    audit_service.log(db, user_id=user.id, action="production_line.delete", entity="production_line", entity_id=line.id, previous=previous)
