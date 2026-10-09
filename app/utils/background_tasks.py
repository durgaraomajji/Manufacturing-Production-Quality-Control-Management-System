"""Optional periodic checks (ENABLE_BACKGROUND_CHECKS=true): low stock, deadlines, delays,
maintenance due, breakdowns and pending approvals are turned into notifications.

For several app workers run this from a single scheduler (cron / Celery beat) instead.
"""
import asyncio
import logging

from app.db.session import SessionLocal
from app.services import notification_service

logger = logging.getLogger("app.background")


def run_checks_once() -> dict[str, int]:
    with SessionLocal() as db:
        counts = notification_service.run_checks(db)
        db.commit()
        return counts


async def periodic_checks(interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            counts = await asyncio.to_thread(run_checks_once)
            if any(counts.values()):
                logger.info("Background checks created notifications: %s", counts)
        except Exception:  # never let the loop die
            logger.exception("Background check failed")
