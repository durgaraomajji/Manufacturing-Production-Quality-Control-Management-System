from datetime import date
from typing import Any, Literal

from fastapi import Query
from pydantic import BaseModel


class ReportFilters:
    """Common query parameters for every report endpoint (FastAPI dependency).

    `status` is interpreted per report: order status (production reports), inspection result
    (quality report), resolution status (defect analysis), material status (material consumption),
    worker status (worker performance), downtime category (downtime analysis).
    """

    def __init__(
        self,
        date_from: date | None = Query(None, description="Inclusive start date"),
        date_to: date | None = Query(None, description="Inclusive end date"),
        plant_id: int | None = None,
        product_id: int | None = None,
        machine_id: int | None = None,
        line_id: int | None = None,
        status: str | None = None,
        search: str | None = Query(None, description="Case-insensitive text search on the row labels"),
        sort_by: str | None = None,
        order: Literal["asc", "desc"] = "desc",
        page: int = Query(1, ge=1),
        size: int = Query(20, ge=1, le=200),
    ):
        self.date_from, self.date_to = date_from, date_to
        self.plant_id, self.product_id, self.machine_id, self.line_id = plant_id, product_id, machine_id, line_id
        self.status, self.search = status, search
        self.sort_by, self.order = sort_by, order
        self.page, self.size = page, size


class ReportPage(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int
    size: int
    pages: int
    summary: dict[str, Any] | None = None
