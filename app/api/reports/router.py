from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DB, perm
from app.core.permissions import P
from app.models.user import User
from app.schemas.dashboard import DashboardRead
from app.schemas.report import ReportFilters, ReportPage
from app.services import dashboard_service, report_service

router = APIRouter(tags=["Dashboard & Reports"])

Filters = Annotated[ReportFilters, Depends()]
Reader = Annotated[User, perm(P.REPORT_READ)]


@router.get("/dashboard", response_model=DashboardRead, summary="Manufacturing dashboard")
def dashboard(db: DB, _: Reader, date_from: date | None = None, date_to: date | None = None, plant_id: int | None = None):
    return dashboard_service.build(db, date_from, date_to, plant_id)


@router.get("/reports/daily-production", response_model=ReportPage)
def daily_production(db: DB, _: Reader, f: Filters):
    return report_service.daily_production(db, f)


@router.get("/reports/monthly-production", response_model=ReportPage)
def monthly_production(db: DB, _: Reader, f: Filters):
    return report_service.monthly_production(db, f)


@router.get("/reports/machine-performance", response_model=ReportPage)
def machine_performance(db: DB, _: Reader, f: Filters):
    return report_service.machine_performance(db, f)


@router.get("/reports/product-wise-production", response_model=ReportPage)
def product_wise(db: DB, _: Reader, f: Filters):
    return report_service.product_wise_production(db, f)


@router.get("/reports/quality", response_model=ReportPage)
def quality(db: DB, _: Reader, f: Filters):
    return report_service.quality_report(db, f)


@router.get("/reports/defect-analysis", response_model=ReportPage)
def defect_analysis(db: DB, _: Reader, f: Filters):
    return report_service.defect_analysis(db, f)


@router.get("/reports/material-consumption", response_model=ReportPage)
def material_consumption(db: DB, _: Reader, f: Filters):
    return report_service.material_consumption(db, f)


@router.get("/reports/worker-performance", response_model=ReportPage)
def worker_performance(db: DB, _: Reader, f: Filters):
    return report_service.worker_performance(db, f)


@router.get("/reports/shift-performance", response_model=ReportPage)
def shift_performance(db: DB, _: Reader, f: Filters):
    return report_service.shift_performance(db, f)


@router.get("/reports/downtime-analysis", response_model=ReportPage)
def downtime_analysis(db: DB, _: Reader, f: Filters):
    return report_service.downtime_analysis(db, f)
