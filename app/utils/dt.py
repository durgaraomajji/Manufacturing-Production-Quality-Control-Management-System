"""Datetime helpers. The whole system stores naive UTC datetimes."""
from datetime import date, datetime, time, timedelta, timezone


def utcnow() -> datetime:
    """Current time as a naive UTC datetime (what we persist)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime) -> datetime:
    """Normalise any datetime (aware or naive) to naive UTC."""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def day_start(d: date) -> datetime:
    return datetime.combine(d, time.min)


def day_end_exclusive(d: date) -> datetime:
    """First instant after day `d` - use with a strict `<` comparison."""
    return datetime.combine(d + timedelta(days=1), time.min)


def overlap_minutes(a_start: datetime, a_end: datetime | None, b_start: datetime, b_end: datetime) -> float:
    """Minutes during which [a_start, a_end) overlaps [b_start, b_end). Open `a_end` means 'now'."""
    a_end = a_end or utcnow()
    start, end = max(a_start, b_start), min(a_end, b_end)
    return max((end - start).total_seconds() / 60.0, 0.0)


def default_window(date_from: date | None, date_to: date | None, days: int = 30) -> tuple[datetime, datetime]:
    """Resolve an optional date range to a (start, end_exclusive) datetime window."""
    end = day_end_exclusive(date_to) if date_to else utcnow()
    start = day_start(date_from) if date_from else end - timedelta(days=days)
    return start, end
