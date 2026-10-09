"""Machine maintenance (Level 14): scheduling, execution, spare parts, cost and due-alerts."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, InvalidTransitionError, NotFoundError
from app.models.machine import Machine
from app.models.maintenance import MaintenanceRecord, SparePartUsage
from app.models.plant import ProductionLine
from app.models.user import User
from app.repositories.maintenance import maintenance_repo
from app.repositories.plant import machine_repo
from app.repositories.user import user_repo
from app.services import audit_service, downtime_service, machine_service
from app.utils.dt import utcnow
from app.utils.enums import (
    AuditAction, DowntimeCategory, MachineStatus, MaintenanceStatus, MaintenanceType, Role,
)


def _validate_technician(db: Session, technician_id: int | None) -> None:
    if technician_id is None:
        return
    tech = user_repo.get(db, technician_id)
    if tech is None:
        raise NotFoundError("Technician", technician_id)
    if tech.role not in (Role.MAINTENANCE_ENGINEER, Role.SUPER_ADMIN) or not tech.is_active:
        raise BusinessRuleError("Technician must be an active maintenance engineer")


def _log(db: Session, user: User, record: MaintenanceRecord, previous: dict | None = None) -> None:
    audit_service.log(db, user_id=user.id, action=AuditAction.MAINTENANCE, entity="maintenance_record", entity_id=record.id,
                      previous=previous, new={**audit_service.snapshot(record), "total_cost": record.total_cost})


def schedule(db: Session, data: dict, user: User) -> MaintenanceRecord:
    machine = machine_repo.get_or_404(db, data["machine_id"])
    if machine.status == MachineStatus.DECOMMISSIONED:
        raise BusinessRuleError("Cannot schedule maintenance for a decommissioned machine")
    _validate_technician(db, data.get("technician_id"))
    mtype = data["maintenance_type"]
    if mtype == MaintenanceType.PREVENTIVE and data["scheduled_date"] < utcnow().date():
        raise BusinessRuleError("Preventive maintenance cannot be scheduled in the past")
    record = maintenance_repo.create(db, {**data, "created_by_id": user.id, "status": MaintenanceStatus.SCHEDULED})
    if mtype == MaintenanceType.BREAKDOWN and machine.status != MachineStatus.BREAKDOWN:
        # reporting a breakdown takes the machine out of service and starts the downtime clock
        if machine.status == MachineStatus.MAINTENANCE:
            pass
        else:
            machine_service.change_status(db, machine, MachineStatus.BREAKDOWN, user, data.get("description"))
        downtime_service.open_downtime(db, machine, DowntimeCategory.MACHINE_BREAKDOWN, data.get("description"), user.id, record.id)
    _log(db, user, record)
    return record


def update(db: Session, record: MaintenanceRecord, data: dict, user: User) -> MaintenanceRecord:
    if record.status != MaintenanceStatus.SCHEDULED:
        raise InvalidTransitionError("Only scheduled maintenance can be edited")
    _validate_technician(db, data.get("technician_id"))
    previous = audit_service.snapshot(record)
    maintenance_repo.update(db, record, data)
    _log(db, user, record, previous)
    return record


def start(db: Session, record: MaintenanceRecord, user: User) -> MaintenanceRecord:
    if record.status != MaintenanceStatus.SCHEDULED:
        raise InvalidTransitionError(f"Cannot start maintenance that is '{record.status.value}'")
    machine = machine_repo.get_or_404(db, record.machine_id)
    if machine.status == MachineStatus.RUNNING:
        raise BusinessRuleError("Machine is running. Stop the running batch before starting maintenance.")
    previous = audit_service.snapshot(record)
    if machine.status != MachineStatus.MAINTENANCE:
        machine_service.change_status(db, machine, MachineStatus.MAINTENANCE, user, "Maintenance started")
    open_dt = downtime_service.get_open(db, machine.id)
    if open_dt and not open_dt.maintenance_id:
        open_dt.maintenance_id = record.id
    record.status = MaintenanceStatus.IN_PROGRESS
    record.started_at = utcnow()
    if record.technician_id is None and user.role == Role.MAINTENANCE_ENGINEER:
        record.technician_id = user.id
    db.flush()
    _log(db, user, record, previous)
    return record


def add_spare_part(db: Session, record: MaintenanceRecord, part: dict, user: User) -> MaintenanceRecord:
    if record.status not in (MaintenanceStatus.SCHEDULED, MaintenanceStatus.IN_PROGRESS):
        raise InvalidTransitionError("Spare parts can only be added to open maintenance records")
    previous = {"parts_cost": record.parts_cost}
    record.spare_parts.append(SparePartUsage(**part))
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.MAINTENANCE, entity="maintenance_record", entity_id=record.id,
                      previous=previous, new={"parts_cost": record.parts_cost, "added_part": part["part_name"]})
    return record


def complete(db: Session, record: MaintenanceRecord, data: dict, user: User) -> MaintenanceRecord:
    if record.status != MaintenanceStatus.IN_PROGRESS:
        raise InvalidTransitionError(f"Cannot complete maintenance that is '{record.status.value}' (start it first)")
    machine = machine_repo.get_or_404(db, record.machine_id)
    previous = audit_service.snapshot(record)
    for part in data.get("spare_parts", []):
        record.spare_parts.append(SparePartUsage(**part))
    record.labor_cost = data.get("labor_cost", 0)
    if data.get("notes"):
        record.notes = data["notes"]
    record.status = MaintenanceStatus.COMPLETED
    record.completed_at = utcnow()
    db.flush()

    if machine.status in (MachineStatus.MAINTENANCE, MachineStatus.BREAKDOWN):
        machine_service.change_status(db, machine, MachineStatus.IDLE, user, "Maintenance completed")
    machine.last_maintenance_date = utcnow().date()
    if machine.maintenance_interval_days:
        machine.next_maintenance_due = machine.last_maintenance_date + timedelta(days=machine.maintenance_interval_days)
    db.flush()
    _log(db, user, record, previous)
    return record


def cancel(db: Session, record: MaintenanceRecord, user: User) -> MaintenanceRecord:
    if record.status not in (MaintenanceStatus.SCHEDULED, MaintenanceStatus.IN_PROGRESS):
        raise InvalidTransitionError(f"Cannot cancel maintenance that is '{record.status.value}'")
    previous = audit_service.snapshot(record)
    was_running = record.status == MaintenanceStatus.IN_PROGRESS
    record.status = MaintenanceStatus.CANCELLED
    machine = machine_repo.get_or_404(db, record.machine_id)
    if was_running and machine.status == MachineStatus.MAINTENANCE:
        machine_service.change_status(db, machine, MachineStatus.IDLE, user, "Maintenance cancelled")
    db.flush()
    _log(db, user, record, previous)
    return record


def history_stmt(machine_id: int):
    return (select(MaintenanceRecord).where(MaintenanceRecord.machine_id == machine_id)
            .order_by(MaintenanceRecord.scheduled_date.desc(), MaintenanceRecord.id.desc()))


def maintenance_due(db: Session, days_ahead: int = 7, plant_id: int | None = None) -> list[dict]:
    """Machines whose maintenance is overdue or due within `days_ahead` days.
    Sources: the machine's own interval schedule and scheduled preventive records."""
    today = utcnow().date()
    horizon = today + timedelta(days=days_ahead)
    due: dict[int, dict] = {}

    def _add(machine: Machine, due_date, source: str, maintenance_id: int | None = None):
        current = due.get(machine.id)
        if current is None or due_date < current["due_date"]:
            due[machine.id] = {
                "machine_id": machine.id, "machine_code": machine.machine_code, "machine_name": machine.name,
                "due_date": due_date, "days_until_due": (due_date - today).days, "overdue": due_date < today,
                "source": source, "maintenance_id": maintenance_id,
            }

    machine_q = select(Machine).where(Machine.is_deleted.is_(False), Machine.status != MachineStatus.DECOMMISSIONED)
    if plant_id is not None:
        machine_q = machine_q.join(ProductionLine, ProductionLine.id == Machine.line_id).where(ProductionLine.plant_id == plant_id)
    for m in db.scalars(machine_q.where(Machine.next_maintenance_due.is_not(None), Machine.next_maintenance_due <= horizon)).all():
        _add(m, m.next_maintenance_due, "schedule")

    rec_q = (select(MaintenanceRecord, Machine).join(Machine, Machine.id == MaintenanceRecord.machine_id)
             .where(MaintenanceRecord.status == MaintenanceStatus.SCHEDULED,
                    MaintenanceRecord.maintenance_type == MaintenanceType.PREVENTIVE,
                    MaintenanceRecord.scheduled_date <= horizon, Machine.is_deleted.is_(False),
                    Machine.status != MachineStatus.DECOMMISSIONED))
    if plant_id is not None:
        rec_q = rec_q.join(ProductionLine, ProductionLine.id == Machine.line_id).where(ProductionLine.plant_id == plant_id)
    for rec, m in db.execute(rec_q).all():
        _add(m, rec.scheduled_date, "record", rec.id)

    return sorted(due.values(), key=lambda d: d["due_date"])
