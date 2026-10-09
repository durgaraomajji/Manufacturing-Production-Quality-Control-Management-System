from datetime import datetime
from typing import Any

from app.schemas.common import ORMModel
from app.utils.enums import NotificationType


class AuditLogRead(ORMModel):
    id: int
    user_id: int | None
    action: str
    entity: str
    entity_id: str | None
    timestamp: datetime
    previous_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    ip_address: str | None


class NotificationRead(ORMModel):
    id: int
    type: NotificationType
    title: str
    message: str
    severity: str
    entity_type: str | None
    entity_id: int | None
    is_read: bool
    created_at: datetime
