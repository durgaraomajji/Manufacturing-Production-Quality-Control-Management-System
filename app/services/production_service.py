"""Production orders & the approval workflow (Levels 8 and 17).

Approval stages (strictly linear, one step at a time):
  created -> supervisor_reviewed -> material_checked -> production_started
          -> quality_inspected -> production_completed -> manager_approved
Order statuses (draft/scheduled/in_progress/paused/completed/cancelled) move together with the stages
and are validated by the transition table in app/utils/state_machine.py.
"""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import (
    BusinessRuleError, InvalidTransitionError, NotFoundError, PermissionDeniedError,
)
from app.models.approval import ApprovalLog
from app.models.production import ProductionBatch, ProductionOrder
from app.models.user import User
from app.repositories.plant import line_repo
from app.repositories.product import product_repo
from app.repositories.production import order_repo
from app.repositories.user import user_repo
from app.services import audit_service, bom_service, inventory_service, material_service, notification_service
from app.utils.dt import utcnow
from app.utils.enums import (
    ApprovalStage, AuditAction, BatchStatus, LineStatus, MovementType, NotificationType,
    OrderStatus, PlantStatus, ProductStatus, Role,
)
from app.utils.state_machine import assert_order_transition, assert_stage, stage_index


# ---------------------------------------------------------------- helpers
def _snap(order: ProductionOrder) -> dict:
    return audit_service.snapshot(order, ["order_number", "product_id", "quantity", "target_date", "line_id", "priority",
                                          "supervisor_id", "status", "approval_stage"])


def _advance(db: Session, order: ProductionOrder, to_stage: ApprovalStage, user: User, action: str,
             comments: str | None = None, status: OrderStatus | None = None) -> None:
    from_stage = order.approval_stage
    if status is not None and status != order.status:
        assert_order_transition(order.status, status)
        order.status = status
    order.approval_stage = to_stage
    db.add(ApprovalLog(order_id=order.id, from_stage=from_stage, to_stage=to_stage, action=action, user_id=user.id, comments=comments))
    db.flush()


def _validate_supervisor(db: Session, supervisor_id: int | None) -> None:
    if supervisor_id is None:
        return
    sup = user_repo.get(db, supervisor_id)
    if sup is None:
        raise NotFoundError("Supervisor", supervisor_id)
    if sup.role not in (Role.PRODUCTION_SUPERVISOR, Role.PRODUCTION_MANAGER) or not sup.is_active:
        raise BusinessRuleError("Supervisor must be an active production supervisor")


def _assert_line_usable(line) -> None:
    if line.status != LineStatus.ACTIVE:
        raise BusinessRuleError(f"Production line {line.line_code} is {line.status.value}")
    if line.plant.status != PlantStatus.ACTIVE:
        raise BusinessRuleError(f"Plant {line.plant.code} is {line.plant.status.value}; production is not possible")


def _assert_capacity(line, quantity: int, target_date) -> None:
    if line.production_capacity and line.production_capacity > 0:
        days = max((target_date - utcnow().date()).days + 1, 1)
        if quantity > line.production_capacity * days:
            raise BusinessRuleError(
                f"Quantity {quantity} exceeds line capacity: {line.line_code} can produce about "
                f"{int(line.production_capacity * days)} units by {target_date}",
                details={"line_capacity_per_day": line.production_capacity, "available_days": days},
            )


def _next_order_number(db: Session) -> str:
    today = utcnow().strftime("%Y%m%d")
    count = db.scalar(select(func.count()).select_from(ProductionOrder).where(ProductionOrder.order_number.like(f"PO-{today}-%"))) or 0
    return f"PO-{today}-{count + 1:04d}"


# ---------------------------------------------------------------- create / update / delete
def create_order(db: Session, data: dict, user: User) -> ProductionOrder:
    product = product_repo.get_or_404(db, data["product_id"])
    if product.status != ProductStatus.ACTIVE:
        raise BusinessRuleError(f"Product {product.sku} is {product.status.value}")
    line = line_repo.get_or_404(db, data["line_id"])
    _assert_line_usable(line)
    if data["target_date"] < utcnow().date():
        raise BusinessRuleError("Target date cannot be in the past")
    bom = bom_service.active_bom_for_product(db, product.id)
    if bom is None:
        raise BusinessRuleError(f"Product {product.sku} has no active BOM; define and activate one first")
    supervisor_id = data.get("supervisor_id") or line.supervisor_id
    _validate_supervisor(db, supervisor_id)
    _assert_capacity(line, data["quantity"], data["target_date"])

    order = order_repo.create(db, {
        **data, "order_number": _next_order_number(db), "bom_id": bom.id, "supervisor_id": supervisor_id,
        "status": OrderStatus.DRAFT, "approval_stage": ApprovalStage.CREATED, "created_by_id": user.id,
    })
    db.add(ApprovalLog(order_id=order.id, from_stage=None, to_stage=ApprovalStage.CREATED, action="create", user_id=user.id))
    audit_service.log(db, user_id=user.id, action=AuditAction.ORDER_CREATE, entity="production_order", entity_id=order.id, new=_snap(order))
    return order


def update_order(db: Session, order: ProductionOrder, data: dict, user: User) -> ProductionOrder:
    if order.status != OrderStatus.DRAFT:
        raise InvalidTransitionError("Only draft orders can be edited")
    previous = _snap(order)
    line = order.line
    if "line_id" in data:
        line = line_repo.get_or_404(db, data["line_id"])
        _assert_line_usable(line)
    if "supervisor_id" in data:
        _validate_supervisor(db, data["supervisor_id"])
    quantity = data.get("quantity", order.quantity)
    target = data.get("target_date", order.target_date)
    if target < utcnow().date():
        raise BusinessRuleError("Target date cannot be in the past")
    _assert_capacity(line, quantity, target)
    order_repo.update(db, order, data)
    audit_service.log(db, user_id=user.id, action="production_order.update", entity="production_order", entity_id=order.id,
                      previous=previous, new=_snap(order))
    return order


def delete_order(db: Session, order: ProductionOrder, user: User) -> None:
    if order.status not in (OrderStatus.DRAFT, OrderStatus.CANCELLED):
        raise InvalidTransitionError("Only draft or cancelled orders can be deleted")
    previous = _snap(order)
    order_repo.soft_delete_obj(db, order)
    audit_service.log(db, user_id=user.id, action="production_order.delete", entity="production_order", entity_id=order.id, previous=previous)


# ---------------------------------------------------------------- workflow
def review_order(db: Session, order: ProductionOrder, user: User, comments: str | None) -> ProductionOrder:
    """Step 2: supervisor review (draft -> scheduled)."""
    assert_stage(order.approval_stage, ApprovalStage.CREATED, "review the order")
    if user.role == Role.PRODUCTION_SUPERVISOR:
        if order.supervisor_id and order.supervisor_id != user.id:
            raise PermissionDeniedError("Only the supervisor assigned to this order can review it")
        order.supervisor_id = order.supervisor_id or user.id
    previous = _snap(order)
    order.reviewed_by_id, order.reviewed_at = user.id, utcnow()
    _advance(db, order, ApprovalStage.SUPERVISOR_REVIEWED, user, "supervisor_review", comments, OrderStatus.SCHEDULED)
    audit_service.log(db, user_id=user.id, action=AuditAction.ORDER_REVIEW, entity="production_order", entity_id=order.id,
                      previous=previous, new=_snap(order))
    return order


def check_materials(db: Session, order: ProductionOrder, user: User) -> dict:
    """Step 3: material availability check. Advances the stage only when every material is sufficient;
    otherwise the stage is unchanged and low-stock notifications are raised."""
    if order.approval_stage not in (ApprovalStage.SUPERVISOR_REVIEWED, ApprovalStage.MATERIAL_CHECKED) or order.status != OrderStatus.SCHEDULED:
        raise InvalidTransitionError(
            f"Cannot check materials: order is '{order.status.value}' at stage '{order.approval_stage.value}' "
            f"(must be scheduled and supervisor-reviewed)"
        )
    result = material_service.check_availability(db, order)
    previous = _snap(order)
    if result["sufficient"]:
        if order.approval_stage == ApprovalStage.SUPERVISOR_REVIEWED:
            _advance(db, order, ApprovalStage.MATERIAL_CHECKED, user, "material_check", "All materials available")
        message = "All required materials are available"
    else:
        short = [i for i in result["items"] if not i["sufficient"]]
        for item in short:
            notification_service.notify(
                db, NotificationType.LOW_STOCK, f"Material shortage for {order.order_number}",
                f"{item['material_code']}: need {item['required_quantity']}, have {item['available_quantity']} (short by {item['shortage']}).",
                severity="warning", entity_type="material", entity_id=item["material_id"], dedupe_key=f"shortage:{order.id}:{item['material_id']}",
            )
        message = f"Insufficient material: {', '.join(i['material_code'] for i in short)}"
    audit_service.log(db, user_id=user.id, action=AuditAction.ORDER_MATERIAL_CHECK, entity="production_order", entity_id=order.id,
                      previous=previous, new={**_snap(order), "sufficient": result["sufficient"]})
    return {**result, "approval_stage": order.approval_stage, "message": message}


def _begin(db: Session, order: ProductionOrder, user: User, action: str) -> None:
    _assert_line_usable(order.line)
    order.started_at = utcnow()
    _advance(db, order, ApprovalStage.PRODUCTION_STARTED, user, action, status=OrderStatus.IN_PROGRESS)


def start_order(db: Session, order: ProductionOrder, user: User) -> ProductionOrder:
    """Step 4: production start (scheduled -> in progress)."""
    assert_stage(order.approval_stage, ApprovalStage.MATERIAL_CHECKED, "start production")
    previous = _snap(order)
    _begin(db, order, user, "production_start")
    audit_service.log(db, user_id=user.id, action=AuditAction.ORDER_START, entity="production_order", entity_id=order.id,
                      previous=previous, new=_snap(order))
    return order


def ensure_started(db: Session, order: ProductionOrder, user: User) -> None:
    """Starting the first batch implicitly starts the order."""
    if order.approval_stage == ApprovalStage.MATERIAL_CHECKED and order.status == OrderStatus.SCHEDULED:
        start_order(db, order, user)


def on_final_inspection_passed(db: Session, order: ProductionOrder, user: User) -> None:
    """Step 5: a passed final-product inspection moves the order to 'quality_inspected'."""
    if order.approval_stage == ApprovalStage.PRODUCTION_STARTED:
        _advance(db, order, ApprovalStage.QUALITY_INSPECTED, user, "quality_inspection", "Final inspection passed")


def set_status(db: Session, order: ProductionOrder, new_status: OrderStatus, user: User, reason: str | None) -> ProductionOrder:
    """Pause / resume / cancel. Scheduling, starting and completing have dedicated workflow endpoints."""
    if new_status not in (OrderStatus.PAUSED, OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED):
        raise BusinessRuleError("Use the workflow endpoints (review, check-materials, start, complete) for this transition")
    if new_status == OrderStatus.IN_PROGRESS and order.status != OrderStatus.PAUSED:
        raise InvalidTransitionError("Only a paused order can be resumed; use the start endpoint to begin production")
    assert_order_transition(order.status, new_status)
    previous = _snap(order)

    batches = [b for b in order.batches if not b.is_deleted]
    if new_status == OrderStatus.CANCELLED:
        if any(b.status == BatchStatus.IN_PROGRESS for b in batches):
            raise BusinessRuleError("Complete or cancel the in-progress batches before cancelling the order")
        for b in batches:
            if b.status == BatchStatus.PLANNED:
                b.status = BatchStatus.CANCELLED
    if new_status == OrderStatus.PAUSED and order.approval_stage != ApprovalStage.PRODUCTION_STARTED:
        raise InvalidTransitionError("Only an order in production can be paused")

    order.status = new_status
    if reason:
        order.remarks = f"{(order.remarks + chr(10)) if order.remarks else ''}[{new_status.value}] {reason}"
    db.add(ApprovalLog(order_id=order.id, from_stage=order.approval_stage, to_stage=order.approval_stage,
                       action=f"status_{new_status.value}", user_id=user.id, comments=reason))
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.ORDER_STATUS, entity="production_order", entity_id=order.id,
                      previous=previous, new=_snap(order))
    return order


def complete_order(db: Session, order: ProductionOrder, user: User, comments: str | None) -> ProductionOrder:
    """Step 6: production completion. Books finished goods (and rejects) into inventory."""
    assert_stage(order.approval_stage, ApprovalStage.QUALITY_INSPECTED, "complete production")
    if order.status != OrderStatus.IN_PROGRESS:
        raise InvalidTransitionError(f"Cannot complete an order that is '{order.status.value}'")
    batches = [b for b in order.batches if not b.is_deleted and b.status != BatchStatus.CANCELLED]
    if not batches or not any(b.status == BatchStatus.COMPLETED for b in batches):
        raise BusinessRuleError("At least one batch must be completed before the order can be completed")
    if any(b.status in (BatchStatus.PLANNED, BatchStatus.IN_PROGRESS) for b in batches):
        raise BusinessRuleError("All batches must be completed or cancelled before the order can be completed")

    previous = _snap(order)
    produced, rejected = order.produced_quantity, order.rejected_quantity
    if produced > 0:
        inventory_service.apply_product_movement(
            db, order.product, MovementType.FINISHED_GOODS, produced, user_id=user.id,
            reference_type="production_order", reference_id=order.id, remarks=f"Finished goods from {order.order_number}",
        )
    if rejected > 0:
        inventory_service.apply_product_movement(
            db, order.product, MovementType.REJECTED_GOODS, 0, quantity=rejected, user_id=user.id,
            reference_type="production_order", reference_id=order.id, remarks=f"Rejected units from {order.order_number}",
        )
    order.completed_at = utcnow()
    _advance(db, order, ApprovalStage.PRODUCTION_COMPLETED, user, "production_complete", comments, OrderStatus.COMPLETED)
    audit_service.log(db, user_id=user.id, action=AuditAction.ORDER_COMPLETE, entity="production_order", entity_id=order.id,
                      previous=previous, new={**_snap(order), "produced": produced, "rejected": rejected})
    notification_service.notify(
        db, NotificationType.APPROVAL_PENDING, f"Approval pending: {order.order_number}",
        f"Order {order.order_number} is complete ({produced} good / {rejected} rejected) and awaits manager approval.",
        entity_type="production_order", entity_id=order.id, dedupe_key=f"approval:{order.id}",
    )
    return order


def approve_order(db: Session, order: ProductionOrder, user: User, comments: str | None) -> ProductionOrder:
    """Step 7: manager approval - the final workflow step."""
    assert_stage(order.approval_stage, ApprovalStage.PRODUCTION_COMPLETED, "approve the order")
    previous = _snap(order)
    order.approved_by_id, order.approved_at = user.id, utcnow()
    _advance(db, order, ApprovalStage.MANAGER_APPROVED, user, "manager_approval", comments)
    audit_service.log(db, user_id=user.id, action=AuditAction.ORDER_APPROVE, entity="production_order", entity_id=order.id,
                      previous=previous, new=_snap(order))
    return order


def approval_history(db: Session, order_id: int) -> list[ApprovalLog]:
    return list(db.scalars(select(ApprovalLog).where(ApprovalLog.order_id == order_id).order_by(ApprovalLog.id)).all())
