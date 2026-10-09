from typing import Annotated

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.api.deps import DB, LQ, perm
from app.core.permissions import P
from app.models.machine import Machine
from app.models.plant import ProductionLine
from app.models.user import User
from app.repositories.plant import machine_repo
from app.schemas.common import Page
from app.schemas.machine import MachineCreate, MachineRead, MachineStatusUpdate, MachineUpdate
from app.services import machine_service
from app.utils.enums import MachineStatus

router = APIRouter(prefix="/machines", tags=["Machines"])


@router.post("", response_model=MachineRead, status_code=201)
def create_machine(body: MachineCreate, db: DB, user: Annotated[User, perm(P.MACHINE_WRITE)]):
    machine = machine_service.create_machine(db, body.model_dump(), user)
    db.commit()
    return machine


@router.get("", response_model=Page[MachineRead])
def list_machines(q: LQ, db: DB, _: Annotated[User, perm(P.MASTER_READ)], line_id: int | None = None,
                  plant_id: int | None = None, status: MachineStatus | None = None, machine_type: str | None = None):
    conditions = []
    if plant_id is not None:
        conditions.append(Machine.line_id.in_(select(ProductionLine.id).where(ProductionLine.plant_id == plant_id)))
    return machine_repo.list(db, **q.kwargs(), conditions=conditions,
                             filters={"line_id": line_id, "status": status, "machine_type": machine_type})


@router.get("/{machine_id}", response_model=MachineRead)
def get_machine(machine_id: int, db: DB, _: Annotated[User, perm(P.MASTER_READ)]):
    return machine_repo.get_or_404(db, machine_id)


@router.patch("/{machine_id}", response_model=MachineRead)
def update_machine(machine_id: int, body: MachineUpdate, db: DB, user: Annotated[User, perm(P.MACHINE_WRITE)]):
    machine = machine_service.update_machine(db, machine_repo.get_or_404(db, machine_id), body.model_dump(exclude_unset=True), user)
    db.commit()
    return machine


@router.patch("/{machine_id}/status", response_model=MachineRead,
              summary="Change machine status (breakdown / maintenance open a downtime record automatically)")
def update_status(machine_id: int, body: MachineStatusUpdate, db: DB, user: Annotated[User, perm(P.MACHINE_STATUS)]):
    machine = machine_service.change_status(db, machine_repo.get_or_404(db, machine_id), body.status, user, body.reason)
    db.commit()
    return machine


@router.delete("/{machine_id}", status_code=204)
def delete_machine(machine_id: int, db: DB, user: Annotated[User, perm(P.MACHINE_WRITE)]):
    machine_service.delete_machine(db, machine_repo.get_or_404(db, machine_id), user)
    db.commit()
    return Response(status_code=204)
