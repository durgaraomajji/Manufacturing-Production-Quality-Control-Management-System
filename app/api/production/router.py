from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select

from app.api.deps import DB, LQ, CurrentUser, perm
from app.core.exceptions import PermissionDeniedError
from app.core.permissions import P, has_permission
from app.models.plant import ProductionLine
from app.models.production import BatchWorker, ProductionBatch, ProductionOrder, ProductionOutputLog
from app.models.user import User
from app.repositories.production import batch_repo, order_repo, output_log_repo, shift_repo, worker_repo
from app.schemas.common import Page
from app.schemas.production import (
    ApprovalLogRead, BatchCreate, BatchRead, BatchWorkersAssign, MaterialAvailability, MaterialCheckResult, OrderCreate,
    OrderRead, OrderStatusChange, OrderUpdate, OutputLogRead, OutputRecord, WorkflowAction,
)
from app.schemas.report import ReportFilters
from app.schemas.worker import ShiftCreate, ShiftRead, ShiftUpdate, WorkerCreate, WorkerRead, WorkerUpdate
from app.services import batch_service, material_service, production_service, report_service, worker_service
from app.utils.enums import (
    ApprovalStage, BatchStatus, OrderPriority, OrderStatus, WorkerStatus,
)
from app.utils.pagination import paginate

router = APIRouter(prefix="/production", tags=["Production"])


# ================================================================== orders
@router.post("/orders", response_model=OrderRead, status_code=201)
def create_order(body: OrderCreate, db: DB, user: Annotated[User, perm(P.ORDER_CREATE)]):
    order = production_service.create_order(db, body.model_dump(), user)
    db.commit()
    return order


@router.get("/orders", response_model=Page[OrderRead])
def list_orders(
    q: LQ, db: DB, _: Annotated[User, perm(P.REPORT_READ)], status: OrderStatus | None = None,
    priority: OrderPriority | None = None, product_id: int | None = None, line_id: int | None = None,
    plant_id: int | None = None, supervisor_id: int | None = None, approval_stage: ApprovalStage | None = None,
    target_from: date | None = None, target_to: date | None = None,
):
    conditions = []
    if plant_id is not None:
        conditions.append(ProductionOrder.line_id.in_(select(ProductionLine.id).where(ProductionLine.plant_id == plant_id)))
    if target_from:
        conditions.append(ProductionOrder.target_date >= target_from)
    if target_to:
        conditions.append(ProductionOrder.target_date <= target_to)
    return order_repo.list(db, **q.kwargs(), conditions=conditions, filters={
        "status": status, "priority": priority, "product_id": product_id, "line_id": line_id,
        "supervisor_id": supervisor_id, "approval_stage": approval_stage})


@router.get("/orders/{order_id}", response_model=OrderRead)
def get_order(order_id: int, db: DB, _: Annotated[User, perm(P.REPORT_READ)]):
    return order_repo.get_or_404(db, order_id)


@router.patch("/orders/{order_id}", response_model=OrderRead, summary="Edit a draft order")
def update_order(order_id: int, body: OrderUpdate, db: DB, user: Annotated[User, perm(P.ORDER_MANAGE)]):
    order = production_service.update_order(db, order_repo.get_or_404(db, order_id), body.model_dump(exclude_unset=True), user)
    db.commit()
    return order


@router.delete("/orders/{order_id}", status_code=204, summary="Delete a draft or cancelled order")
def delete_order(order_id: int, db: DB, user: Annotated[User, perm(P.ORDER_MANAGE)]):
    production_service.delete_order(db, order_repo.get_or_404(db, order_id), user)
    db.commit()
    return Response(status_code=204)


# ---- approval workflow (Level 17): review -> check-materials -> start -> (inspection) -> complete -> approve
@router.post("/orders/{order_id}/review", response_model=OrderRead, summary="Workflow 1/5: supervisor review (draft -> scheduled)")
def review_order(order_id: int, db: DB, user: Annotated[User, perm(P.ORDER_REVIEW)], body: WorkflowAction | None = None):
    order = production_service.review_order(db, order_repo.get_or_404(db, order_id), user, body.comments if body else None)
    db.commit()
    return order


@router.get("/orders/{order_id}/material-availability", response_model=MaterialAvailability,
            summary="Read-only check of BOM requirements vs. stock")
def material_availability(order_id: int, db: DB, _: Annotated[User, perm(P.REPORT_READ)]):
    return material_service.check_availability(db, order_repo.get_or_404(db, order_id))


@router.post("/orders/{order_id}/check-materials", response_model=MaterialCheckResult,
             summary="Workflow 2/5: material availability check (advances the stage only if everything is available)")
def check_materials(order_id: int, db: DB, user: Annotated[User, perm(P.ORDER_REVIEW)]):
    result = production_service.check_materials(db, order_repo.get_or_404(db, order_id), user)
    db.commit()
    return result


@router.post("/orders/{order_id}/start", response_model=OrderRead, summary="Workflow 3/5: production start")
def start_order(order_id: int, db: DB, user: Annotated[User, perm(P.ORDER_EXECUTE)]):
    order = production_service.start_order(db, order_repo.get_or_404(db, order_id), user)
    db.commit()
    return order


@router.post("/orders/{order_id}/status", response_model=OrderRead, summary="Pause, resume or cancel an order")
def change_order_status(order_id: int, body: OrderStatusChange, db: DB, user: CurrentUser):
    needed = P.ORDER_MANAGE if body.status == OrderStatus.CANCELLED else P.ORDER_EXECUTE
    if not has_permission(user.role, needed):
        raise PermissionDeniedError(f"Role '{user.role.value}' cannot set an order to '{body.status.value}'")
    order = production_service.set_status(db, order_repo.get_or_404(db, order_id), body.status, user, body.reason)
    db.commit()
    return order


@router.post("/orders/{order_id}/complete", response_model=OrderRead,
             summary="Workflow 4/5: production completion (books finished goods into inventory)")
def complete_order(order_id: int, db: DB, user: Annotated[User, perm(P.ORDER_EXECUTE)], body: WorkflowAction | None = None):
    order = production_service.complete_order(db, order_repo.get_or_404(db, order_id), user, body.comments if body else None)
    db.commit()
    return order


@router.post("/orders/{order_id}/approve", response_model=OrderRead, summary="Workflow 5/5: manager approval")
def approve_order(order_id: int, db: DB, user: Annotated[User, perm(P.ORDER_APPROVE)], body: WorkflowAction | None = None):
    order = production_service.approve_order(db, order_repo.get_or_404(db, order_id), user, body.comments if body else None)
    db.commit()
    return order


@router.get("/orders/{order_id}/approval-history", response_model=list[ApprovalLogRead])
def approval_history(order_id: int, db: DB, _: Annotated[User, perm(P.REPORT_READ)]):
    order_repo.get_or_404(db, order_id)
    return production_service.approval_history(db, order_id)


# ================================================================== batches
@router.post("/batches", response_model=BatchRead, status_code=201)
def create_batch(body: BatchCreate, db: DB, user: Annotated[User, perm(P.ORDER_EXECUTE)]):
    batch = batch_service.create_batch(db, body.model_dump(), user)
    db.commit()
    return batch


@router.get("/batches", response_model=Page[BatchRead])
def list_batches(q: LQ, db: DB, _: Annotated[User, perm(P.REPORT_READ)], order_id: int | None = None,
                 line_id: int | None = None, machine_id: int | None = None, status: BatchStatus | None = None,
                 supervisor_id: int | None = None, shift_id: int | None = None):
    return batch_repo.list(db, **q.kwargs(), filters={
        "order_id": order_id, "line_id": line_id, "machine_id": machine_id, "status": status,
        "supervisor_id": supervisor_id, "shift_id": shift_id})


@router.get("/my-batches", response_model=Page[BatchRead], summary="Batches the logged-in worker is assigned to")
def my_batches(q: LQ, db: DB, user: CurrentUser):
    worker = worker_repo.get_by(db, user_id=user.id)
    stmt = select(ProductionBatch).where(ProductionBatch.is_deleted.is_(False), ProductionBatch.id.in_(
        select(BatchWorker.batch_id).where(BatchWorker.worker_id == (worker.id if worker else -1)))
    ).order_by(ProductionBatch.id.desc())
    return paginate(db, stmt, q.page, q.size)


@router.get("/batches/{batch_id}", response_model=BatchRead)
def get_batch(batch_id: int, db: DB, _: Annotated[User, perm(P.REPORT_READ)]):
    return batch_repo.get_or_404(db, batch_id)


@router.get("/batches/{batch_id}/workers", response_model=list[WorkerRead])
def batch_workers(batch_id: int, db: DB, _: Annotated[User, perm(P.REPORT_READ)]):
    batch = batch_repo.get_or_404(db, batch_id)
    return [worker_repo.get(db, bw.worker_id) for bw in batch.workers]


@router.post("/batches/{batch_id}/workers", response_model=BatchRead, status_code=201, summary="Assign workers to a batch")
def assign_workers(batch_id: int, body: BatchWorkersAssign, db: DB, user: Annotated[User, perm(P.ORDER_EXECUTE)]):
    batch = batch_service.assign_workers(db, batch_repo.get_or_404(db, batch_id), body.worker_ids, user)
    db.commit()
    return batch


@router.delete("/batches/{batch_id}/workers/{worker_id}", response_model=BatchRead)
def remove_worker(batch_id: int, worker_id: int, db: DB, user: Annotated[User, perm(P.ORDER_EXECUTE)]):
    batch = batch_service.remove_worker(db, batch_repo.get_or_404(db, batch_id), worker_id, user)
    db.commit()
    return batch


@router.post("/batches/{batch_id}/start", response_model=BatchRead, summary="Start a batch (issues BOM materials from stock)")
def start_batch(batch_id: int, db: DB, user: Annotated[User, perm(P.ORDER_EXECUTE)]):
    batch = batch_service.start_batch(db, batch_repo.get_or_404(db, batch_id), user)
    db.commit()
    return batch


@router.post("/batches/{batch_id}/output", response_model=BatchRead, summary="Record produced / rejected quantities")
def record_output(batch_id: int, body: OutputRecord, db: DB, user: Annotated[User, perm(P.ORDER_EXECUTE)]):
    batch = batch_service.record_output(db, batch_repo.get_or_404(db, batch_id), body.model_dump(), user)
    db.commit()
    return batch


@router.get("/batches/{batch_id}/output-logs", response_model=Page[OutputLogRead])
def output_logs(batch_id: int, q: LQ, db: DB, _: Annotated[User, perm(P.REPORT_READ)]):
    batch_repo.get_or_404(db, batch_id)
    return output_log_repo.list(db, page=q.page, size=q.size, sort_by="recorded_at", order=q.order, filters={"batch_id": batch_id})


@router.post("/batches/{batch_id}/complete", response_model=BatchRead)
def complete_batch(batch_id: int, db: DB, user: Annotated[User, perm(P.ORDER_EXECUTE)]):
    batch = batch_service.complete_batch(db, batch_repo.get_or_404(db, batch_id), user)
    db.commit()
    return batch


@router.post("/batches/{batch_id}/cancel", response_model=BatchRead)
def cancel_batch(batch_id: int, db: DB, user: Annotated[User, perm(P.ORDER_EXECUTE)]):
    batch = batch_service.cancel_batch(db, batch_repo.get_or_404(db, batch_id), user)
    db.commit()
    return batch


# ================================================================== workers
@router.post("/workers", response_model=WorkerRead, status_code=201)
def create_worker(body: WorkerCreate, db: DB, user: Annotated[User, perm(P.WORKER_WRITE)]):
    worker = worker_service.create_worker(db, body.model_dump(), user)
    db.commit()
    return worker


@router.get("/workers", response_model=Page[WorkerRead])
def list_workers(q: LQ, db: DB, _: Annotated[User, perm(P.REPORT_READ)], status: WorkerStatus | None = None,
                 shift_id: int | None = None, line_id: int | None = None, department: str | None = None,
                 skill: str | None = None):
    return worker_repo.list(db, **q.kwargs(), filters={
        "status": status, "shift_id": shift_id, "line_id": line_id, "department": department, "skill": skill})


@router.get("/workers/{worker_id}", response_model=WorkerRead)
def get_worker(worker_id: int, db: DB, _: Annotated[User, perm(P.REPORT_READ)]):
    return worker_repo.get_or_404(db, worker_id)


@router.patch("/workers/{worker_id}", response_model=WorkerRead)
def update_worker(worker_id: int, body: WorkerUpdate, db: DB, user: Annotated[User, perm(P.WORKER_WRITE)]):
    worker = worker_service.update_worker(db, worker_repo.get_or_404(db, worker_id), body.model_dump(exclude_unset=True), user)
    db.commit()
    return worker


@router.delete("/workers/{worker_id}", status_code=204)
def delete_worker(worker_id: int, db: DB, user: Annotated[User, perm(P.WORKER_WRITE)]):
    worker = worker_repo.get_or_404(db, worker_id)
    worker_repo.soft_delete_obj(db, worker)
    db.commit()
    return Response(status_code=204)


# ================================================================== shifts
@router.get("/shifts", response_model=Page[ShiftRead])
def list_shifts(q: LQ, db: DB, _: Annotated[User, perm(P.MASTER_READ)]):
    return shift_repo.list(db, page=q.page, size=q.size, sort_by="id", order="asc")


@router.post("/shifts", response_model=ShiftRead, status_code=201)
def create_shift(body: ShiftCreate, db: DB, user: Annotated[User, perm(P.SHIFT_WRITE)]):
    shift = worker_service.create_shift(db, body.model_dump(), user)
    db.commit()
    return shift


@router.patch("/shifts/{shift_id}", response_model=ShiftRead)
def update_shift(shift_id: int, body: ShiftUpdate, db: DB, user: Annotated[User, perm(P.SHIFT_WRITE)]):
    shift = worker_service.update_shift(db, shift_repo.get_or_404(db, shift_id), body.model_dump(exclude_unset=True), user)
    db.commit()
    return shift


@router.get("/shifts/{shift_id}/performance", summary="Output, machine usage and efficiency for one shift")
def shift_performance(shift_id: int, db: DB, _: Annotated[User, perm(P.REPORT_READ)], f: Annotated[ReportFilters, Depends()]):
    shift_repo.get_or_404(db, shift_id)
    return report_service.single_shift_performance(db, shift_id, f)
