from app.models.audit import AuditLog
from app.models.notification import Notification
from app.repositories.base import BaseRepository

audit_repo = BaseRepository(AuditLog, "Audit log", search_fields=("action", "entity"))
notification_repo = BaseRepository(Notification, "Notification", search_fields=("title", "message"))
