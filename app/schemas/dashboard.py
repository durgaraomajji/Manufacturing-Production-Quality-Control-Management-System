from datetime import date
from typing import Any

from pydantic import BaseModel


class OrderStats(BaseModel):
    total: int
    active: int
    completed: int
    by_status: dict[str, int]


class ProductionStats(BaseModel):
    daily_production: int
    monthly_production: int
    production_efficiency_percent: float
    rejection_rate_percent: float


class MachineStats(BaseModel):
    machine_utilization_percent: float
    machine_downtime_percent: float
    by_status: dict[str, int]


class QualityStats(BaseModel):
    total_inspections: int
    passed: int
    failed: int
    quality_pass_percent: float


class MaterialStats(BaseModel):
    consumption: list[dict[str, Any]]
    low_stock: list[dict[str, Any]]


class DefectStats(BaseModel):
    total: int
    open: int
    by_severity: dict[str, int]
    by_status: dict[str, int]


class DashboardRead(BaseModel):
    window_start: date
    window_end: date
    orders: OrderStats
    production: ProductionStats
    machines: MachineStats
    quality: QualityStats
    materials: MaterialStats
    maintenance_due: list[dict[str, Any]]
    defects: DefectStats
