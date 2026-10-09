from datetime import date
from typing import Annotated

from fastapi import APIRouter

from app.api.deps import DB, LQ, perm
from app.core.permissions import P
from app.models.quality import Defect, Inspection
from app.models.user import User
from app.repositories.quality import defect_repo, inspection_repo
from app.schemas.common import Page
from app.schemas.quality import DefectCreate, DefectRead, DefectUpdate, InspectionCreate, InspectionRead
from app.services import quality_service
from app.utils.dt import day_end_exclusive, day_start
from app.utils.enums import InspectionResult, InspectionType, ResolutionStatus, Severity

router = APIRouter(tags=["Quality"])


@router.post("/inspections", response_model=InspectionRead, status_code=201)
def create_inspection(body: InspectionCreate, db: DB, user: Annotated[User, perm(P.INSPECTION_WRITE)]):
    data = body.model_dump()
    data["parameters"] = [p.model_dump() for p in body.parameters]
    inspection = quality_service.create_inspection(db, data, user)
    db.commit()
    return inspection


@router.get("/inspections", response_model=Page[InspectionRead])
def list_inspections(q: LQ, db: DB, _: Annotated[User, perm(P.REPORT_READ)], batch_id: int | None = None,
                     inspection_type: InspectionType | None = None, result: InspectionResult | None = None,
                     inspector_id: int | None = None, date_from: date | None = None, date_to: date | None = None):
    conditions = []
    if date_from:
        conditions.append(Inspection.inspection_date >= day_start(date_from))
    if date_to:
        conditions.append(Inspection.inspection_date < day_end_exclusive(date_to))
    return inspection_repo.list(db, **{**q.kwargs(), "sort_by": q.sort_by or "inspection_date"}, conditions=conditions, filters={
        "batch_id": batch_id, "inspection_type": inspection_type, "result": result, "inspector_id": inspector_id})


@router.get("/inspections/{inspection_id}", response_model=InspectionRead)
def get_inspection(inspection_id: int, db: DB, _: Annotated[User, perm(P.REPORT_READ)]):
    return inspection_repo.get_or_404(db, inspection_id)


@router.post("/defects", response_model=DefectRead, status_code=201)
def create_defect(body: DefectCreate, db: DB, user: Annotated[User, perm(P.DEFECT_WRITE)]):
    defect = quality_service.create_defect(db, body.model_dump(), user)
    db.commit()
    return defect


@router.get("/defects", response_model=Page[DefectRead])
def list_defects(q: LQ, db: DB, _: Annotated[User, perm(P.REPORT_READ)], batch_id: int | None = None,
                 product_id: int | None = None, severity: Severity | None = None,
                 resolution_status: ResolutionStatus | None = None, date_from: date | None = None,
                 date_to: date | None = None):
    conditions = []
    if date_from:
        conditions.append(Defect.created_at >= day_start(date_from))
    if date_to:
        conditions.append(Defect.created_at < day_end_exclusive(date_to))
    return defect_repo.list(db, **q.kwargs(), conditions=conditions, filters={
        "batch_id": batch_id, "product_id": product_id, "severity": severity, "resolution_status": resolution_status})


@router.get("/defects/{defect_id}", response_model=DefectRead)
def get_defect(defect_id: int, db: DB, _: Annotated[User, perm(P.REPORT_READ)]):
    return defect_repo.get_or_404(db, defect_id)


@router.patch("/defects/{defect_id}", response_model=DefectRead,
              summary="Update a defect / move it through open -> in_progress -> resolved -> closed")
def update_defect(defect_id: int, body: DefectUpdate, db: DB, user: Annotated[User, perm(P.DEFECT_WRITE)]):
    defect = quality_service.update_defect(db, defect_repo.get_or_404(db, defect_id), body.model_dump(exclude_unset=True), user)
    db.commit()
    return defect
