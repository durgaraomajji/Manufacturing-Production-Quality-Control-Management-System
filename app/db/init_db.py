"""Idempotent bootstrap data: the three standard shifts and the first Super Admin."""
import logging
from datetime import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models.user import User
from app.models.worker import Shift
from app.utils.enums import Role, ShiftName

logger = logging.getLogger("app.init_db")

DEFAULT_SHIFTS = {
    ShiftName.MORNING: (time(6, 0), time(14, 0)),
    ShiftName.EVENING: (time(14, 0), time(22, 0)),
    ShiftName.NIGHT: (time(22, 0), time(6, 0)),
}


def seed_defaults(db: Session) -> None:
    existing = set(db.scalars(select(Shift.name)).all())
    for name, (start, end) in DEFAULT_SHIFTS.items():
        if name not in existing:
            db.add(Shift(name=name, start_time=start, end_time=end))

    if not db.scalar(select(func.count()).select_from(User)):
        db.add(User(
            email=settings.FIRST_SUPERUSER_EMAIL.lower(),
            full_name=settings.FIRST_SUPERUSER_NAME,
            hashed_password=hash_password(settings.FIRST_SUPERUSER_PASSWORD),
            role=Role.SUPER_ADMIN,
            is_active=True,
        ))
        logger.info("Created first super admin %s", settings.FIRST_SUPERUSER_EMAIL)
    db.commit()
