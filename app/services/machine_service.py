"""Machine registration and status management (Level 7)."""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, ConflictError
from app.models.machine import Machine
from app.models.production import ProductionBatch
from app.models.user import User
from app.repositories.plant import line_repo, machine_repo
from app.services import audit_service, downtime_service, notification_service
from app.utils.dt import utcnow
from app.utils.enums import AuditAction, BatchStatus, DowntimeCategory, LineStatus, MachineStatus, NotificationType


def _schedule_next_due(machine: Machine) -> None:
    if machine.maintenance_interval_days:
        base = machine.last_maintenance_date or machine.installation_date or utcnow().date()
        machine.next_maintenance_due = base + timedelta(days=machine.maintenance_interval_days)
    else:
        machine.next_maintenance_due = None


def create_machine(db: Session, data: dict, user: User) -> Machine:
    line = line_repo.get_or_404(db, data["line_id"])
    if line.status == LineStatus.INACTIVE:
        raise BusinessRuleError("Cannot register a machine on an inactive production line")
    if machine_repo.exists(db, machine_code=data["machine_code"]):
        raise ConflictError(f"Machine code '{data['machine_code']}' already exists")
    if data.get("status") in (MachineStatus.RUNNING, MachineStatus.BREAKDOWN):
        raise BusinessRuleError("A new machine must be registered as idle, in maintenance or decommissioned")
    machine = machine_repo.create(db, data)
    _schedule_next_due(machine)
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.MACHINE_CREATE, entity="machine", entity_id=machine.id,
                      new=audit_service.snapshot(machine))
    return machine


def update_machine(db: Session, machine: Machine, data: dict, user: User) -> Machine:
    if "line_id" in data and data["line_id"] != machine.line_id:
        line_repo.get_or_404(db, data["line_id"])
        if machine.status == MachineStatus.RUNNING:
            raise BusinessRuleError("Stop the machine before moving it to another line")
    previous = audit_service.snapshot(machine)
    machine_repo.update(db, machine, data)
    if "maintenance_interval_days" in data:
        _schedule_next_due(machine)
    audit_service.log(db, user_id=user.id, action=AuditAction.MACHINE_CREATE.value.replace("create", "update"),
                      entity="machine", entity_id=machine.id, previous=previous, new=audit_service.snapshot(machine))
    return machine


def change_status(db: Session, machine: Machine, new_status: MachineStatus, user: User | None, reason: str | None = None) -> Machine:
    """Single place that changes a machine's status. Keeps downtime records, notifications and the
    audit trail consistent with the status change."""
    previous = machine.status
    if previous == new_status:
        return machine
    if previous == MachineStatus.DECOMMISSIONED:
        raise BusinessRuleError("A decommissioned machine cannot be reactivated")
    user_id = user.id if user else None

    if new_status == MachineStatus.DECOMMISSIONED:
        busy = db.scalar(select(func.count()).select_from(ProductionBatch).where(
            ProductionBatch.machine_id == machine.id, ProductionBatch.status == BatchStatus.IN_PROGRESS))
        if busy:
            raise BusinessRuleError("Machine is running an in-progress batch")
    if new_status == MachineStatus.RUNNING and previous in (MachineStatus.BREAKDOWN, MachineStatus.MAINTENANCE):
        raise BusinessRuleError(f"Machine is in {previous.value}; return it to idle first")

    machine.status = new_status
    db.flush()

    if new_status == MachineStatus.BREAKDOWN:
        downtime_service.open_downtime(db, machine, DowntimeCategory.MACHINE_BREAKDOWN, reason or "Machine breakdown", user_id)
        notification_service.notify(
            db, NotificationType.MACHINE_BREAKDOWN, f"Machine breakdown: {machine.machine_code}",
            f"{machine.name} reported a breakdown. {reason or ''}".strip(), severity="critical",
            entity_type="machine", entity_id=machine.id, dedupe_key=f"breakdown:{machine.id}",
        )
    elif new_status == MachineStatus.MAINTENANCE:
        downtime_service.open_downtime(db, machine, DowntimeCategory.MAINTENANCE, reason or "Machine under maintenance", user_id)
    elif new_status in (MachineStatus.IDLE, MachineStatus.RUNNING, MachineStatus.DECOMMISSIONED):
        downtime_service.close_open_for_machine(db, machine.id)

    audit_service.log(
        db, user_id=user_id, action=AuditAction.MACHINE_STATUS, entity="machine", entity_id=machine.id,
        previous={"status": previous.value}, new={"status": new_status.value, "reason": reason},
    )
    return machine


def delete_machine(db: Session, machine: Machine, user: User) -> None:
    busy = db.scalar(select(func.count()).select_from(ProductionBatch).where(
        ProductionBatch.machine_id == machine.id, ProductionBatch.status.in_((BatchStatus.PLANNED, BatchStatus.IN_PROGRESS))))
    if busy or machine.status == MachineStatus.RUNNING:
        raise ConflictError("Machine is assigned to planned or in-progress batches")
    previous = audit_service.snapshot(machine)
    machine_repo.soft_delete_obj(db, machine)
    audit_service.log(db, user_id=user.id, action="machine.delete", entity="machine", entity_id=machine.id, previous=previous)
