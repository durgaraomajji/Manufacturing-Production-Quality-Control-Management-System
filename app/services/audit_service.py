"""Audit trail (Level 20). Entries are added to the caller's transaction, so an action and its
audit record are committed - or rolled back - together."""
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def snapshot(obj: Any, fields: list[str] | None = None) -> dict[str, Any]:
    """JSON-safe dict of an ORM object's column values (optionally limited to `fields`)."""
    columns = [c.key for c in obj.__table__.columns if c.key not in ("hashed_password",)]
    names = fields or columns
    return jsonable_encoder({name: getattr(obj, name) for name in names if name in columns})


def log(
    db: Session,
    *,
    user_id: int | None,
    action: str,
    entity: str,
    entity_id: int | str | None = None,
    previous: dict[str, Any] | None = None,
    new: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        action=str(action),
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        previous_value=jsonable_encoder(previous) if previous is not None else None,
        new_value=jsonable_encoder(new) if new is not None else None,
        ip_address=ip,
    )
    db.add(entry)
    return entry
