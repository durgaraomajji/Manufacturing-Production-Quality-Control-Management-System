"""Worker profiles and shifts (Levels 10 and 11)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models.user import User
from app.models.worker import Shift, Worker
from app.repositories.plant import line_repo
from app.repositories.production import shift_repo, worker_repo
from app.repositories.user import user_repo
from app.services import audit_service


def _validate_refs(db: Session, data: dict, current_worker_id: int | None = None) -> None:
    if data.get("shift_id") is not None:
        shift = shift_repo.get(db, data["shift_id"])
        if shift is None:
            raise NotFoundError("Shift", data["shift_id"])
        if not shift.is_active:
            raise BusinessRuleError("Shift is not active")
    if data.get("line_id") is not None:
        line_repo.get_or_404(db, data["line_id"])
    if data.get("user_id") is not None:
        if user_repo.get(db, data["user_id"]) is None:
            raise NotFoundError("User", data["user_id"])
        linked = worker_repo.get_by(db, user_id=data["user_id"])
        if linked and linked.id != current_worker_id:
            raise ConflictError("That user account is already linked to another worker profile")


def create_worker(db: Session, data: dict, user: User) -> Worker:
    if worker_repo.exists(db, employee_code=data["employee_code"]):
        raise ConflictError(f"Employee code '{data['employee_code']}' already exists")
    _validate_refs(db, data)
    worker = worker_repo.create(db, data)
    audit_service.log(db, user_id=user.id, action="worker.create", entity="worker", entity_id=worker.id, new=audit_service.snapshot(worker))
    return worker


def update_worker(db: Session, worker: Worker, data: dict, user: User) -> Worker:
    _validate_refs(db, data, worker.id)
    previous = audit_service.snapshot(worker)
    worker_repo.update(db, worker, data)
    audit_service.log(db, user_id=user.id, action="worker.update", entity="worker", entity_id=worker.id,
                      previous=previous, new=audit_service.snapshot(worker))
    return worker


def create_shift(db: Session, data: dict, user: User) -> Shift:
    if db.scalars(select(Shift).where(Shift.name == data["name"])).first():
        raise ConflictError(f"Shift '{data['name'].value}' already exists")
    if data["start_time"] == data["end_time"]:
        raise BusinessRuleError("Shift start and end time must differ")
    shift = shift_repo.create(db, data)
    audit_service.log(db, user_id=user.id, action="shift.create", entity="shift", entity_id=shift.id, new=audit_service.snapshot(shift))
    return shift


def update_shift(db: Session, shift: Shift, data: dict, user: User) -> Shift:
    start, end = data.get("start_time", shift.start_time), data.get("end_time", shift.end_time)
    if start == end:
        raise BusinessRuleError("Shift start and end time must differ")
    previous = audit_service.snapshot(shift)
    shift_repo.update(db, shift, data)
    audit_service.log(db, user_id=user.id, action="shift.update", entity="shift", entity_id=shift.id,
                      previous=previous, new=audit_service.snapshot(shift))
    return shift
