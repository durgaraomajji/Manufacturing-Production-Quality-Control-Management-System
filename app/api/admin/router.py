from datetime import date
from typing import Annotated

from fastapi import APIRouter

from app.api.deps import DB, LQ, CurrentUser, perm
from app.core.exceptions import NotFoundError
from app.core.permissions import P
from app.models.audit import AuditLog
from app.models.user import User
from app.repositories.ops import audit_repo, notification_repo
from app.schemas.audit import AuditLogRead, NotificationRead
from app.schemas.common import Message, Page
from app.services import notification_service
from app.utils.dt import day_end_exclusive, day_start
from app.utils.enums import NotificationType

router = APIRouter(tags=["Audit & Notifications"])


# ------------------------------------------------------------------ audit logs (Level 20)
@router.get("/admin/audit-logs", response_model=Page[AuditLogRead])
def list_audit_logs(q: LQ, db: DB, _: Annotated[User, perm(P.AUDIT_READ)], user_id: int | None = None,
                    action: str | None = None, entity: str | None = None, entity_id: str | None = None,
                    date_from: date | None = None, date_to: date | None = None):
    conditions = []
    if date_from:
        conditions.append(AuditLog.timestamp >= day_start(date_from))
    if date_to:
        conditions.append(AuditLog.timestamp < day_end_exclusive(date_to))
    return audit_repo.list(db, **q.kwargs(), conditions=conditions,
                           filters={"user_id": user_id, "action": action, "entity": entity, "entity_id": entity_id})


@router.get("/admin/audit-logs/{log_id}", response_model=AuditLogRead)
def get_audit_log(log_id: int, db: DB, _: Annotated[User, perm(P.AUDIT_READ)]):
    return audit_repo.get_or_404(db, log_id)


# ------------------------------------------------------------------ notifications (Level 21)
@router.get("/notifications", response_model=Page[NotificationRead], summary="Notifications of the logged-in user")
def list_notifications(q: LQ, db: DB, user: CurrentUser, is_read: bool | None = None, type: NotificationType | None = None):
    return notification_repo.list(db, **q.kwargs(), filters={"user_id": user.id, "is_read": is_read, "type": type})


@router.get("/notifications/unread-count")
def unread_count(db: DB, user: CurrentUser):
    page = notification_repo.list(db, page=1, size=1, filters={"user_id": user.id, "is_read": False})
    return {"unread": page["total"]}


@router.post("/notifications/read-all", response_model=Message)
def read_all(db: DB, user: CurrentUser):
    from sqlalchemy import update
    from app.models.notification import Notification
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False)).values(is_read=True))
    db.commit()
    return Message(message="All notifications marked as read")


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead)
def mark_read(notification_id: int, db: DB, user: CurrentUser):
    notification = notification_repo.get(db, notification_id)
    if notification is None or notification.user_id != user.id:
        raise NotFoundError("Notification", notification_id)
    notification.is_read = True
    db.commit()
    return notification


@router.post("/admin/notifications/run-checks", summary="Scan for low stock, deadlines, delays, maintenance due, ... now")
def run_checks(db: DB, _: Annotated[User, perm(P.NOTIFICATION_MANAGE)]):
    counts = notification_service.run_checks(db)
    db.commit()
    return {"created": counts, "total": sum(counts.values())}
