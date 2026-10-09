from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DB, LQ, perm
from app.core.config import settings
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.core.permissions import P
from app.models.maintenance import Downtime
from app.models.user import User
from app.repositories.maintenance import downtime_repo, maintenance_repo
from app.repositories.plant import machine_repo
from app.schemas.common import Page
from app.schemas.maintenance import (
    DowntimeClose, DowntimeCreate, DowntimePercentage, DowntimeRead, MaintenanceComplete, MaintenanceCreate,
    MaintenanceDue, MaintenanceRead, MaintenanceUpdate, SparePartIn,
)
from app.services import downtime_service, maintenance_service
from app.utils.dt import day_end_exclusive, day_start
from app.utils.enums import DowntimeCategory, MaintenanceStatus, MaintenanceType
from app.utils.pagination import paginate

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])
downtime_router = APIRouter(prefix="/downtimes", tags=["Downtime"])


# ------------------------------------------------------------------ maintenance
@router.post("", response_model=MaintenanceRead, status_code=201,
             summary="Schedule maintenance (a breakdown record also takes the machine out of service)")
def schedule_maintenance(body: MaintenanceCreate, db: DB, user: Annotated[User, perm(P.MAINTENANCE_WRITE)]):
    record = maintenance_service.schedule(db, body.model_dump(), user)
    db.commit()
    return record


@router.get("", response_model=Page[MaintenanceRead])
def list_maintenance(q: LQ, db: DB, _: Annotated[User, perm(P.REPORT_READ)], machine_id: int | None = None,
                     status: MaintenanceStatus | None = None, maintenance_type: MaintenanceType | None = None,
                     technician_id: int | None = None, date_from: date | None = None, date_to: date | None = None):
    from app.models.maintenance import MaintenanceRecord
    conditions = []
    if date_from:
        conditions.append(MaintenanceRecord.scheduled_date >= date_from)
    if date_to:
        conditions.append(MaintenanceRecord.scheduled_date <= date_to)
    return maintenance_repo.list(db, **{**q.kwargs(), "sort_by": q.sort_by or "scheduled_date"}, conditions=conditions, filters={
        "machine_id": machine_id, "status": status, "maintenance_type": maintenance_type, "technician_id": technician_id})


@router.get("/due", response_model=list[MaintenanceDue], summary="Maintenance alerts: overdue or due within N days")
def maintenance_due(db: DB, _: Annotated[User, perm(P.REPORT_READ)],
                    days_ahead: int = Query(default=settings.MAINTENANCE_DUE_WARNING_DAYS, ge=0, le=365),
                    plant_id: int | None = None):
    return maintenance_service.maintenance_due(db, days_ahead, plant_id)


@router.get("/machines/{machine_id}/history", response_model=Page[MaintenanceRead], summary="Maintenance history of a machine")
def machine_history(machine_id: int, q: LQ, db: DB, _: Annotated[User, perm(P.REPORT_READ)]):
    machine_repo.get_or_404(db, machine_id)
    return paginate(db, maintenance_service.history_stmt(machine_id), q.page, q.size)


@router.get("/{maintenance_id}", response_model=MaintenanceRead)
def get_maintenance(maintenance_id: int, db: DB, _: Annotated[User, perm(P.REPORT_READ)]):
    return maintenance_repo.get_or_404(db, maintenance_id)


@router.patch("/{maintenance_id}", response_model=MaintenanceRead)
def update_maintenance(maintenance_id: int, body: MaintenanceUpdate, db: DB, user: Annotated[User, perm(P.MAINTENANCE_WRITE)]):
    record = maintenance_service.update(db, maintenance_repo.get_or_404(db, maintenance_id), body.model_dump(exclude_unset=True), user)
    db.commit()
    return record


@router.post("/{maintenance_id}/start", response_model=MaintenanceRead)
def start_maintenance(maintenance_id: int, db: DB, user: Annotated[User, perm(P.MAINTENANCE_WRITE)]):
    record = maintenance_service.start(db, maintenance_repo.get_or_404(db, maintenance_id), user)
    db.commit()
    return record


@router.post("/{maintenance_id}/spare-parts", response_model=MaintenanceRead, status_code=201)
def add_spare_part(maintenance_id: int, body: SparePartIn, db: DB, user: Annotated[User, perm(P.MAINTENANCE_WRITE)]):
    record = maintenance_service.add_spare_part(db, maintenance_repo.get_or_404(db, maintenance_id), body.model_dump(), user)
    db.commit()
    return record


@router.post("/{maintenance_id}/complete", response_model=MaintenanceRead, summary="Complete (records labour + spare-part cost)")
def complete_maintenance(maintenance_id: int, body: MaintenanceComplete, db: DB, user: Annotated[User, perm(P.MAINTENANCE_WRITE)]):
    record = maintenance_service.complete(db, maintenance_repo.get_or_404(db, maintenance_id), body.model_dump(), user)
    db.commit()
    return record


@router.post("/{maintenance_id}/cancel", response_model=MaintenanceRead)
def cancel_maintenance(maintenance_id: int, db: DB, user: Annotated[User, perm(P.MAINTENANCE_WRITE)]):
    record = maintenance_service.cancel(db, maintenance_repo.get_or_404(db, maintenance_id), user)
    db.commit()
    return record


# ------------------------------------------------------------------ downtime
@downtime_router.post("", response_model=DowntimeRead, status_code=201)
def create_downtime(body: DowntimeCreate, db: DB, user: Annotated[User, perm(P.DOWNTIME_WRITE)]):
    downtime = downtime_service.create_manual(db, body.model_dump(), user)
    db.commit()
    return downtime


@downtime_router.get("", response_model=Page[DowntimeRead])
def list_downtimes(q: LQ, db: DB, _: Annotated[User, perm(P.REPORT_READ)], machine_id: int | None = None,
                   line_id: int | None = None, category: DowntimeCategory | None = None, open_only: bool = False,
                   date_from: date | None = None, date_to: date | None = None):
    conditions = []
    if open_only:
        conditions.append(Downtime.end_time.is_(None))
    if date_from:
        conditions.append(Downtime.start_time >= day_start(date_from))
    if date_to:
        conditions.append(Downtime.start_time < day_end_exclusive(date_to))
    return downtime_repo.list(db, **{**q.kwargs(), "sort_by": q.sort_by or "start_time"}, conditions=conditions,
                              filters={"machine_id": machine_id, "line_id": line_id, "category": category})


@downtime_router.get("/machines/{machine_id}/percentage", response_model=DowntimePercentage,
                     summary="Machine downtime % over a window (default: last 30 days)")
def machine_downtime_percentage(machine_id: int, db: DB, _: Annotated[User, perm(P.REPORT_READ)],
                                date_from: date | None = None, date_to: date | None = None):
    machine_repo.get_or_404(db, machine_id)
    return downtime_service.downtime_percentage(db, machine_id, date_from, date_to)


@downtime_router.get("/{downtime_id}", response_model=DowntimeRead)
def get_downtime(downtime_id: int, db: DB, _: Annotated[User, perm(P.REPORT_READ)]):
    return downtime_repo.get_or_404(db, downtime_id)


@downtime_router.post("/{downtime_id}/close", response_model=DowntimeRead, summary="End an open downtime and compute its duration")
def close_downtime(downtime_id: int, db: DB, user: Annotated[User, perm(P.DOWNTIME_WRITE)], body: DowntimeClose | None = None):
    downtime = downtime_repo.get_or_404(db, downtime_id)
    if downtime.end_time is not None:
        raise BusinessRuleError("Downtime is already closed")
    downtime_service.close_downtime(db, downtime, body.end_time if body else None)
    db.commit()
    return downtime
