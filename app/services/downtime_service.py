"""Machine downtime tracking (Level 15)."""
from collections import defaultdict
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, ConflictError
from app.models.machine import Machine
from app.models.maintenance import Downtime
from app.models.user import User
from app.services import audit_service
from app.utils.dt import default_window, overlap_minutes, utcnow
from app.utils.enums import AuditAction, DowntimeCategory


def _duration(start: datetime, end: datetime) -> float:
    return round((end - start).total_seconds() / 60.0, 2)


def get_open(db: Session, machine_id: int) -> Downtime | None:
    return db.scalars(select(Downtime).where(Downtime.machine_id == machine_id, Downtime.end_time.is_(None))).first()


def open_downtime(db: Session, machine: Machine, category: DowntimeCategory, reason: str | None,
                  user_id: int | None = None, maintenance_id: int | None = None, start_time: datetime | None = None) -> Downtime:
    existing = get_open(db, machine.id)
    if existing:
        if maintenance_id and not existing.maintenance_id:
            existing.maintenance_id = maintenance_id
        return existing
    downtime = Downtime(
        machine_id=machine.id, line_id=machine.line_id, category=category, reason=reason,
        start_time=start_time or utcnow(), responsible_user_id=user_id, maintenance_id=maintenance_id,
    )
    db.add(downtime)
    db.flush()
    return downtime


def close_downtime(db: Session, downtime: Downtime, end_time: datetime | None = None) -> Downtime:
    end = end_time or utcnow()
    if end < downtime.start_time:
        raise BusinessRuleError("Downtime end time cannot be before its start time")
    downtime.end_time = end
    downtime.duration_minutes = _duration(downtime.start_time, end)
    db.flush()
    return downtime


def close_open_for_machine(db: Session, machine_id: int, end_time: datetime | None = None) -> None:
    open_dt = get_open(db, machine_id)
    if open_dt:
        close_downtime(db, open_dt, end_time)


def create_manual(db: Session, data: dict, user: User) -> Downtime:
    machine = db.get(Machine, data["machine_id"])
    if machine is None or machine.is_deleted:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Machine", data["machine_id"])
    end = data.get("end_time")
    if end is None and get_open(db, machine.id):
        raise ConflictError("This machine already has an open downtime record; close it first")
    if end is not None and end < data["start_time"]:
        raise BusinessRuleError("Downtime end time cannot be before its start time")
    downtime = Downtime(
        machine_id=machine.id, line_id=machine.line_id, category=data["category"], reason=data.get("reason"),
        start_time=data["start_time"], end_time=end, duration_minutes=_duration(data["start_time"], end) if end else None,
        responsible_user_id=data.get("responsible_user_id") or user.id,
    )
    db.add(downtime)
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.DOWNTIME, entity="downtime", entity_id=downtime.id,
                      new=audit_service.snapshot(downtime))
    return downtime


def downtime_minutes_by_machine(db: Session, machine_ids: list[int], start: datetime, end: datetime) -> dict[int, float]:
    """Downtime minutes per machine, clipped to the window [start, end). Open downtime counts up to now."""
    if not machine_ids:
        return {}
    rows = db.scalars(select(Downtime).where(
        Downtime.machine_id.in_(machine_ids), Downtime.start_time < end,
        or_(Downtime.end_time.is_(None), Downtime.end_time > start),
    )).all()
    totals: dict[int, float] = defaultdict(float)
    for d in rows:
        totals[d.machine_id] += overlap_minutes(d.start_time, d.end_time, start, end)
    return dict(totals)


def downtime_percentage(db: Session, machine_id: int, date_from=None, date_to=None) -> dict:
    """Downtime % = downtime minutes in the window / window minutes x 100 (default window: last 30 days)."""
    start, end = default_window(date_from, date_to)
    window = max((end - start).total_seconds() / 60.0, 1.0)
    minutes = min(downtime_minutes_by_machine(db, [machine_id], start, end).get(machine_id, 0.0), window)
    return {
        "machine_id": machine_id, "window_start": start, "window_end": end, "window_minutes": round(window, 2),
        "downtime_minutes": round(minutes, 2), "downtime_percentage": round(minutes / window * 100, 2),
    }
