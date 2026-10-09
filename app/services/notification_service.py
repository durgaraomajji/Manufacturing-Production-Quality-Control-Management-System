"""Notifications (Level 21) plus the periodic checks that raise them."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.machine import Machine
from app.models.material import Material
from app.models.notification import Notification
from app.models.production import ProductionBatch, ProductionOrder
from app.models.user import User
from app.utils.dt import utcnow
from app.utils.enums import (
    ApprovalStage, BatchStatus, MachineStatus, NotificationType, OrderStatus, Role,
)

# Who should hear about what (Super Admin always receives everything)
RECIPIENTS: dict[NotificationType, list[Role]] = {
    NotificationType.LOW_STOCK: [Role.STORE_MANAGER, Role.PRODUCTION_MANAGER],
    NotificationType.PRODUCTION_DEADLINE: [Role.PRODUCTION_MANAGER, Role.PRODUCTION_SUPERVISOR],
    NotificationType.MACHINE_BREAKDOWN: [Role.MAINTENANCE_ENGINEER, Role.PLANT_MANAGER, Role.PRODUCTION_MANAGER],
    NotificationType.MAINTENANCE_DUE: [Role.MAINTENANCE_ENGINEER, Role.PLANT_MANAGER],
    NotificationType.CRITICAL_DEFECT: [Role.QUALITY_MANAGER, Role.PLANT_MANAGER, Role.PRODUCTION_MANAGER],
    NotificationType.HIGH_REJECTION: [Role.QUALITY_MANAGER, Role.PRODUCTION_MANAGER, Role.PRODUCTION_SUPERVISOR],
    NotificationType.PRODUCTION_DELAY: [Role.PRODUCTION_MANAGER, Role.PLANT_MANAGER],
    NotificationType.APPROVAL_PENDING: [Role.PRODUCTION_MANAGER, Role.PLANT_MANAGER],
}


def notify(
    db: Session,
    ntype: NotificationType,
    title: str,
    message: str,
    *,
    severity: str = "info",
    entity_type: str | None = None,
    entity_id: int | None = None,
    dedupe_key: str | None = None,
) -> int:
    """Create one notification per recipient. If `dedupe_key` is given, a recipient who still has
    an unread notification with that key is skipped. Returns the number of notifications created."""
    roles = RECIPIENTS.get(ntype, []) + [Role.SUPER_ADMIN]
    user_ids = db.scalars(
        select(User.id).where(User.role.in_(roles), User.is_active.is_(True), User.is_deleted.is_(False))
    ).all()
    created = 0
    for uid in user_ids:
        if dedupe_key:
            already = db.scalars(
                select(Notification.id).where(
                    Notification.user_id == uid, Notification.dedupe_key == dedupe_key, Notification.is_read.is_(False)
                ).limit(1)
            ).first()
            if already:
                continue
        db.add(Notification(
            user_id=uid, type=ntype, title=title, message=message, severity=severity,
            entity_type=entity_type, entity_id=entity_id, dedupe_key=dedupe_key,
        ))
        created += 1
    db.flush()
    return created


def notify_high_rejection(db: Session, batch: ProductionBatch) -> int:
    total = batch.produced_quantity + batch.rejected_quantity
    if total >= settings.HIGH_REJECTION_MIN_UNITS and batch.rejection_percentage > settings.HIGH_REJECTION_THRESHOLD_PERCENT:
        return notify(
            db, NotificationType.HIGH_REJECTION, f"High rejection rate on {batch.batch_number}",
            f"Batch {batch.batch_number} has a rejection rate of {batch.rejection_percentage}% "
            f"(threshold {settings.HIGH_REJECTION_THRESHOLD_PERCENT}%).",
            severity="warning", entity_type="production_batch", entity_id=batch.id,
            dedupe_key=f"high_rejection:{batch.id}",
        )
    return 0


def run_checks(db: Session) -> dict[str, int]:
    """Scan the system and raise notifications for conditions that are not event-driven.
    Safe to call repeatedly: notifications are de-duplicated while unread."""
    from app.services import maintenance_service  # local import avoids a cycle

    now = utcnow()
    today = now.date()
    counts = {t.value: 0 for t in NotificationType}

    # low raw-material stock
    for m in db.scalars(select(Material).where(Material.is_deleted.is_(False))).all():
        if m.is_low_stock:
            counts["low_stock"] += notify(
                db, NotificationType.LOW_STOCK, f"Low stock: {m.code}",
                f"{m.name} has {m.available_quantity} {m.unit} left (minimum {m.minimum_stock_level}, reorder at {m.reorder_level}).",
                severity="warning", entity_type="material", entity_id=m.id, dedupe_key=f"low_stock:{m.id}",
            )

    open_states = (OrderStatus.DRAFT, OrderStatus.SCHEDULED, OrderStatus.IN_PROGRESS, OrderStatus.PAUSED)
    orders = db.scalars(select(ProductionOrder).where(
        ProductionOrder.is_deleted.is_(False), ProductionOrder.status.in_(open_states))).all()
    for o in orders:
        days_left = (o.target_date - today).days
        if days_left < 0:
            counts["production_delay"] += notify(
                db, NotificationType.PRODUCTION_DELAY, f"Production delayed: {o.order_number}",
                f"Order {o.order_number} passed its target date ({o.target_date}) and is still '{o.status.value}'.",
                severity="critical", entity_type="production_order", entity_id=o.id, dedupe_key=f"delay:{o.id}",
            )
        elif days_left <= settings.DEADLINE_WARNING_DAYS:
            counts["production_deadline"] += notify(
                db, NotificationType.PRODUCTION_DEADLINE, f"Deadline approaching: {o.order_number}",
                f"Order {o.order_number} is due in {days_left} day(s) ({o.target_date}).",
                severity="warning", entity_type="production_order", entity_id=o.id, dedupe_key=f"deadline:{o.id}",
            )

    # completed but waiting for manager approval
    pending = db.scalars(select(ProductionOrder).where(
        ProductionOrder.is_deleted.is_(False), ProductionOrder.approval_stage == ApprovalStage.PRODUCTION_COMPLETED)).all()
    for o in pending:
        counts["approval_pending"] += notify(
            db, NotificationType.APPROVAL_PENDING, f"Approval pending: {o.order_number}",
            f"Order {o.order_number} is complete and awaiting manager approval.",
            entity_type="production_order", entity_id=o.id, dedupe_key=f"approval:{o.id}",
        )

    # machines in breakdown
    for m in db.scalars(select(Machine).where(Machine.is_deleted.is_(False), Machine.status == MachineStatus.BREAKDOWN)).all():
        counts["machine_breakdown"] += notify(
            db, NotificationType.MACHINE_BREAKDOWN, f"Machine breakdown: {m.machine_code}",
            f"{m.name} is in breakdown and needs attention.", severity="critical",
            entity_type="machine", entity_id=m.id, dedupe_key=f"breakdown:{m.id}",
        )

    # maintenance due
    for due in maintenance_service.maintenance_due(db, days_ahead=settings.MAINTENANCE_DUE_WARNING_DAYS):
        counts["maintenance_due"] += notify(
            db, NotificationType.MAINTENANCE_DUE, f"Maintenance due: {due['machine_code']}",
            f"{due['machine_name']} maintenance is {'overdue' if due['overdue'] else 'due'} on {due['due_date']}.",
            severity="critical" if due["overdue"] else "warning",
            entity_type="machine", entity_id=due["machine_id"], dedupe_key=f"maint_due:{due['machine_id']}",
        )

    # high rejection on recent batches
    for b in db.scalars(select(ProductionBatch).where(
            ProductionBatch.is_deleted.is_(False), ProductionBatch.status != BatchStatus.CANCELLED,
            ProductionBatch.created_at >= now - timedelta(days=30))).all():
        counts["high_rejection"] += notify_high_rejection(db, b)

    db.flush()
    return counts
