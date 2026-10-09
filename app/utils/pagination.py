"""Pagination / sorting helpers shared by repositories and report services."""
from math import ceil
from typing import Any, Callable

from fastapi import Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError


class PageParams:
    """FastAPI dependency: ?page=1&size=20"""

    def __init__(self, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200)):
        self.page = page
        self.size = size


def page_dict(items: list, total: int, page: int, size: int) -> dict:
    return {"items": items, "total": total, "page": page, "size": size, "pages": ceil(total / size) if total else 0}


def paginate(db: Session, stmt: Select, page: int, size: int) -> dict:
    """Paginate a `select(Model)` statement."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = db.scalars(stmt.limit(size).offset((page - 1) * size)).all()
    return page_dict(list(items), total, page, size)


def paginate_list(rows: list, page: int, size: int) -> dict:
    start = (page - 1) * size
    return page_dict(rows[start:start + size], len(rows), page, size)


def sort_rows(rows: list[dict], sort_by: str | None, order: str, allowed: set[str], default: str) -> list[dict]:
    key = sort_by or default
    if key not in allowed:
        raise BusinessRuleError(f"Invalid sort field '{key}'. Allowed: {', '.join(sorted(allowed))}")
    return sorted(rows, key=lambda r: (r.get(key) is None, r.get(key)), reverse=(order == "desc"))


def map_page(page: dict, fn: Callable[[Any], Any]) -> dict:
    return {**page, "items": [fn(i) for i in page["items"]]}
