"""Production batches: creation, worker assignment, execution and output (Levels 9-11).

Materials are issued to the shop floor when a batch starts: BOM quantity x planned quantity is
consumed from stock in the same transaction as the start (all-or-nothing).
"""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BusinessRuleError, ConflictError, InvalidTransitionError, NotFoundError
from app.models.material import Material
from app.models.production import BatchWorker, ProductionBatch, ProductionOutputLog
from app.models.user import User
from app.models.worker import Shift
from app.repositories.plant import line_repo, machine_repo
from app.repositories.production import batch_repo, order_repo, shift_repo, worker_repo
from app.services import audit_service, inventory_service, machine_service, notification_service, production_service
from app.utils.dt import utcnow
from app.utils.enums import (
    ApprovalStage, AuditAction, BatchStatus, MachineStatus, MovementType, OrderStatus, WorkerStatus,
)


def current_shift_id(db: Session, at: datetime | None = None) -> int | None:
    local = (at or utcnow()) + timedelta(minutes=settings.SHIFT_UTC_OFFSET_MINUTES)
    for shift in db.scalars(select(Shift).where(Shift.is_active.is_(True))).all():
        if shift.contains(local.time()):
            return shift.id
    return None


def _snap(batch: ProductionBatch) -> dict:
    return audit_service.snapshot(batch, [
        "batch_number", "order_id", "planned_quantity", "produced_quantity", "rejected_quantity",
        "start_time", "end_time", "line_id", "machine_id", "supervisor_id", "shift_id", "status"])


def _assert_machine_usable(machine, line_id: int) -> None:
    if machine.line_id != line_id:
        raise BusinessRuleError(f"Machine {machine.machine_code} does not belong to the batch's production line")
    if machine.status in (MachineStatus.BREAKDOWN, MachineStatus.MAINTENANCE, MachineStatus.DECOMMISSIONED):
        raise BusinessRuleError(f"Machine {machine.machine_code} is {machine.status.value} and cannot be used")


# ---------------------------------------------------------------- create
def create_batch(db: Session, data: dict, user: User) -> ProductionBatch:
    order = order_repo.get_or_404(db, data["order_id"])
    if order.status not in (OrderStatus.SCHEDULED, OrderStatus.IN_PROGRESS) or order.approval_stage not in (
            ApprovalStage.MATERIAL_CHECKED, ApprovalStage.PRODUCTION_STARTED):
        raise InvalidTransitionError(
            "Batches can only be created once the order is reviewed and its materials are checked "
            f"(order is '{order.status.value}' at stage '{order.approval_stage.value}')")
    planned_total = db.scalar(select(func.coalesce(func.sum(ProductionBatch.planned_quantity), 0)).where(
        ProductionBatch.order_id == order.id, ProductionBatch.is_deleted.is_(False),
        ProductionBatch.status != BatchStatus.CANCELLED))
    if planned_total + data["planned_quantity"] > order.quantity:
        raise BusinessRuleError(
            f"Planned quantity exceeds the order: {planned_total} already planned, "
            f"{order.quantity - planned_total} remaining of {order.quantity}")

    line_id = data.get("line_id") or order.line_id
    production_service._assert_line_usable(line_repo.get_or_404(db, line_id))
    if data.get("machine_id") is not None:
        _assert_machine_usable(machine_repo.get_or_404(db, data["machine_id"]), line_id)
    supervisor_id = data.get("supervisor_id") or order.supervisor_id
    production_service._validate_supervisor(db, supervisor_id)
    if data.get("shift_id") is not None and shift_repo.get(db, data["shift_id"]) is None:
        raise NotFoundError("Shift", data["shift_id"])

    seq = (db.scalar(select(func.count()).select_from(ProductionBatch).where(ProductionBatch.order_id == order.id)) or 0) + 1
    batch = batch_repo.create(db, {
        **data, "line_id": line_id, "supervisor_id": supervisor_id,
        "batch_number": f"{order.order_number}-B{seq:02d}", "status": BatchStatus.PLANNED,
    })
    audit_service.log(db, user_id=user.id, action=AuditAction.BATCH_CREATE, entity="production_batch", entity_id=batch.id, new=_snap(batch))
    return batch


# ---------------------------------------------------------------- workers
def assign_workers(db: Session, batch: ProductionBatch, worker_ids: list[int], user: User) -> ProductionBatch:
    if batch.status not in (BatchStatus.PLANNED, BatchStatus.IN_PROGRESS):
        raise InvalidTransitionError(f"Cannot assign workers to a {batch.status.value} batch")
    if len(set(worker_ids)) != len(worker_ids):
        raise BusinessRuleError("Duplicate worker ids in request")
    already = {bw.worker_id for bw in batch.workers}
    for wid in worker_ids:
        worker = worker_repo.get_or_404(db, wid)
        if worker.status != WorkerStatus.ACTIVE:
            raise BusinessRuleError(f"Worker {worker.employee_code} is {worker.status.value}")
        if worker.line_id is not None and worker.line_id != batch.line_id:
            raise BusinessRuleError(f"Worker {worker.employee_code} is assigned to a different production line")
        if wid in already:
            raise ConflictError(f"Worker {worker.employee_code} is already assigned to this batch")
        busy = db.scalar(select(func.count()).select_from(BatchWorker).join(
            ProductionBatch, ProductionBatch.id == BatchWorker.batch_id).where(
            BatchWorker.worker_id == wid, ProductionBatch.status == BatchStatus.IN_PROGRESS, ProductionBatch.id != batch.id))
        if busy:
            raise ConflictError(f"Worker {worker.employee_code} is working on another in-progress batch")
    previous = {"worker_ids": sorted(already)}
    for wid in worker_ids:
        batch.workers.append(BatchWorker(worker_id=wid, assigned_by_id=user.id))
    db.flush()
    audit_service.log(db, user_id=user.id, action="batch.workers_assigned", entity="production_batch", entity_id=batch.id,
                      previous=previous, new={"worker_ids": sorted(already | set(worker_ids))})
    return batch


def remove_worker(db: Session, batch: ProductionBatch, worker_id: int, user: User) -> ProductionBatch:
    link = next((bw for bw in batch.workers if bw.worker_id == worker_id), None)
    if link is None:
        raise NotFoundError("Batch worker", worker_id)
    if batch.status not in (BatchStatus.PLANNED, BatchStatus.IN_PROGRESS):
        raise InvalidTransitionError(f"Cannot change workers of a {batch.status.value} batch")
    if batch.status == BatchStatus.IN_PROGRESS and len(batch.workers) == 1:
        raise BusinessRuleError("An in-progress batch needs at least one worker")
    previous = {"worker_ids": sorted(bw.worker_id for bw in batch.workers)}
    batch.workers.remove(link)
    db.flush()
    audit_service.log(db, user_id=user.id, action="batch.workers_removed", entity="production_batch", entity_id=batch.id,
                      previous=previous, new={"worker_ids": sorted(bw.worker_id for bw in batch.workers)})
    return batch


# ---------------------------------------------------------------- execution
def start_batch(db: Session, batch: ProductionBatch, user: User) -> ProductionBatch:
    if batch.status != BatchStatus.PLANNED:
        raise InvalidTransitionError(f"Cannot start a batch that is '{batch.status.value}'")
    order = batch.order
    if order.status == OrderStatus.PAUSED:
        raise BusinessRuleError("The production order is paused; resume it first")
    production_service.ensure_started(db, order, user)
    if order.status != OrderStatus.IN_PROGRESS:
        raise InvalidTransitionError("The production order has not been cleared for production")
    production_service._assert_line_usable(line_repo.get_or_404(db, batch.line_id))
    if not batch.workers:
        raise BusinessRuleError("Assign at least one worker before starting the batch")

    previous = _snap(batch)
    machine = None
    if batch.machine_id is not None:
        machine = machine_repo.get_or_404(db, batch.machine_id)
        _assert_machine_usable(machine, batch.line_id)

    # issue raw materials for the planned quantity (raises InsufficientStockError -> whole start rolls back)
    for item in order.bom.items:
        material = db.get(Material, item.material_id)
        quantity = round(item.quantity_per_unit * batch.planned_quantity, 3)
        inventory_service.apply_material_movement(
            db, material, MovementType.CONSUMPTION, -quantity, user_id=user.id, batch_id=batch.id,
            reference_type="production_batch", reference_id=batch.id,
            remarks=f"Issued to {batch.batch_number} ({batch.planned_quantity} units)")

    if machine is not None:
        machine_service.change_status(db, machine, MachineStatus.RUNNING, user, f"Started {batch.batch_number}")
    batch.status = BatchStatus.IN_PROGRESS
    batch.start_time = utcnow()
    batch.shift_id = batch.shift_id or current_shift_id(db, batch.start_time)
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.BATCH_START, entity="production_batch", entity_id=batch.id,
                      previous=previous, new=_snap(batch))
    return batch


def record_output(db: Session, batch: ProductionBatch, data: dict, user: User) -> ProductionBatch:
    if batch.status != BatchStatus.IN_PROGRESS:
        raise InvalidTransitionError(f"Output can only be recorded on an in-progress batch (batch is '{batch.status.value}')")
    if batch.order.status != OrderStatus.IN_PROGRESS:
        raise BusinessRuleError(f"The production order is {batch.order.status.value}; output cannot be recorded")
    produced, rejected = data.get("produced", 0), data.get("rejected", 0)
    if produced + rejected <= 0:
        raise BusinessRuleError("Record at least one produced or rejected unit")
    total = batch.produced_quantity + batch.rejected_quantity + produced + rejected
    if total > batch.planned_quantity:
        raise BusinessRuleError(
            f"Output exceeds the planned quantity: {batch.produced_quantity + batch.rejected_quantity} already recorded, "
            f"planned {batch.planned_quantity}")
    recorded_at = data.get("recorded_at") or utcnow()
    previous = _snap(batch)
    batch.produced_quantity += produced
    batch.rejected_quantity += rejected
    db.add(ProductionOutputLog(
        batch_id=batch.id, produced=produced, rejected=rejected, recorded_at=recorded_at, recorded_by_id=user.id,
        shift_id=current_shift_id(db, recorded_at) or batch.shift_id, remarks=data.get("remarks")))
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.BATCH_OUTPUT, entity="production_batch", entity_id=batch.id,
                      previous=previous, new=_snap(batch))
    notification_service.notify_high_rejection(db, batch)
    return batch


def complete_batch(db: Session, batch: ProductionBatch, user: User) -> ProductionBatch:
    if batch.status != BatchStatus.IN_PROGRESS:
        raise InvalidTransitionError(f"Cannot complete a batch that is '{batch.status.value}'")
    if batch.produced_quantity + batch.rejected_quantity == 0:
        raise BusinessRuleError("Record production output before completing the batch")
    previous = _snap(batch)
    batch.status = BatchStatus.COMPLETED
    batch.end_time = utcnow()
    if batch.machine_id is not None:
        machine = machine_repo.get_or_404(db, batch.machine_id)
        machine.operating_hours = round((machine.operating_hours or 0) + batch.run_minutes / 60.0, 2)
        still_busy = db.scalar(select(func.count()).select_from(ProductionBatch).where(
            ProductionBatch.machine_id == machine.id, ProductionBatch.status == BatchStatus.IN_PROGRESS,
            ProductionBatch.id != batch.id))
        if machine.status == MachineStatus.RUNNING and not still_busy:
            machine_service.change_status(db, machine, MachineStatus.IDLE, user, f"Completed {batch.batch_number}")
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.BATCH_COMPLETE, entity="production_batch", entity_id=batch.id,
                      previous=previous, new=_snap(batch))
    notification_service.notify_high_rejection(db, batch)
    return batch


def cancel_batch(db: Session, batch: ProductionBatch, user: User) -> ProductionBatch:
    if batch.status != BatchStatus.PLANNED:
        raise InvalidTransitionError("Only planned batches can be cancelled (materials were already issued once a batch starts)")
    previous = _snap(batch)
    batch.status = BatchStatus.CANCELLED
    db.flush()
    audit_service.log(db, user_id=user.id, action="batch.cancel", entity="production_batch", entity_id=batch.id,
                      previous=previous, new=_snap(batch))
    return batch
