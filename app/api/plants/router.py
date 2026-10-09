from typing import Annotated

from fastapi import APIRouter, Response

from app.api.deps import DB, LQ, perm
from app.core.permissions import P
from app.models.plant import ProductionLine
from app.models.user import User
from app.repositories.plant import line_repo, plant_repo
from app.schemas.common import Page
from app.schemas.plant import (
    LineCreate, LineRead, LineUpdate, PlantCreate, PlantManagerAssign, PlantRead, PlantStatusUpdate, PlantUpdate,
)
from app.services import plant_service
from app.utils.enums import LineStatus, PlantStatus

router = APIRouter(tags=["Plants & Production Lines"])


# ------------------------------------------------------------------ plants
@router.post("/plants", response_model=PlantRead, status_code=201)
def create_plant(body: PlantCreate, db: DB, user: Annotated[User, perm(P.PLANT_WRITE)]):
    plant = plant_service.create_plant(db, body.model_dump(), user)
    db.commit()
    return plant


@router.get("/plants", response_model=Page[PlantRead])
def list_plants(q: LQ, db: DB, _: Annotated[User, perm(P.PLANT_READ)], status: PlantStatus | None = None,
                city: str | None = None, manager_id: int | None = None):
    return plant_repo.list(db, **q.kwargs(), filters={"status": status, "city": city, "manager_id": manager_id})


@router.get("/plants/{plant_id}", response_model=PlantRead)
def get_plant(plant_id: int, db: DB, _: Annotated[User, perm(P.PLANT_READ)]):
    return plant_repo.get_or_404(db, plant_id)


@router.patch("/plants/{plant_id}", response_model=PlantRead)
def update_plant(plant_id: int, body: PlantUpdate, db: DB, user: Annotated[User, perm(P.PLANT_WRITE)]):
    plant = plant_service.update_plant(db, plant_repo.get_or_404(db, plant_id), body.model_dump(exclude_unset=True), user)
    db.commit()
    return plant


@router.patch("/plants/{plant_id}/status", response_model=PlantRead)
def update_plant_status(plant_id: int, body: PlantStatusUpdate, db: DB, user: Annotated[User, perm(P.PLANT_WRITE)]):
    plant = plant_service.change_status(db, plant_repo.get_or_404(db, plant_id), body.status, body.reason, user)
    db.commit()
    return plant


@router.put("/plants/{plant_id}/manager", response_model=PlantRead)
def assign_plant_manager(plant_id: int, body: PlantManagerAssign, db: DB, user: Annotated[User, perm(P.PLANT_WRITE)]):
    plant = plant_service.assign_manager(db, plant_repo.get_or_404(db, plant_id), body.manager_id, user)
    db.commit()
    return plant


@router.delete("/plants/{plant_id}", status_code=204)
def delete_plant(plant_id: int, db: DB, user: Annotated[User, perm(P.PLANT_WRITE)]):
    plant_service.delete_plant(db, plant_repo.get_or_404(db, plant_id), user)
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------ production lines
@router.post("/production-lines", response_model=LineRead, status_code=201)
def create_line(body: LineCreate, db: DB, user: Annotated[User, perm(P.LINE_WRITE)]):
    line = plant_service.create_line(db, body.model_dump(), user)
    db.commit()
    return line


@router.get("/production-lines", response_model=Page[LineRead])
def list_lines(q: LQ, db: DB, _: Annotated[User, perm(P.MASTER_READ)], plant_id: int | None = None,
               status: LineStatus | None = None, supervisor_id: int | None = None):
    return line_repo.list(db, **q.kwargs(), filters={"plant_id": plant_id, "status": status, "supervisor_id": supervisor_id})


@router.get("/production-lines/{line_id}", response_model=LineRead)
def get_line(line_id: int, db: DB, _: Annotated[User, perm(P.MASTER_READ)]):
    return line_repo.get_or_404(db, line_id)


@router.patch("/production-lines/{line_id}", response_model=LineRead)
def update_line(line_id: int, body: LineUpdate, db: DB, user: Annotated[User, perm(P.LINE_WRITE)]):
    line = plant_service.update_line(db, line_repo.get_or_404(db, line_id), body.model_dump(exclude_unset=True), user)
    db.commit()
    return line


@router.delete("/production-lines/{line_id}", status_code=204)
def delete_line(line_id: int, db: DB, user: Annotated[User, perm(P.LINE_WRITE)]):
    plant_service.delete_line(db, line_repo.get_or_404(db, line_id), user)
    db.commit()
    return Response(status_code=204)
