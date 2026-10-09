"""Manufacturing dashboard (Level 18).

Windowed figures use [date_from, date_to] (default: last 30 days). Order counts are all-time and the
daily / monthly production figures are anchored to today (UTC). "Active" orders are those that are
scheduled, in progress or paused.
"""
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.inventory import InventoryTransaction
from app.models.machine import Machine
from app.models.material import Material
from app.models.plant import ProductionLine
from app.models.production import ProductionBatch, ProductionOrder, ProductionOutputLog
from app.models.quality import Defect, Inspection
from app.services import downtime_service, material_service, maintenance_service
from app.utils.dt import day_start, default_window, overlap_minutes, utcnow
from app.utils.enums import (
    BatchStatus, InspectionResult, MachineStatus, MovementType, OrderStatus, ResolutionStatus, Severity,
)

ACTIVE_STATES = (OrderStatus.SCHEDULED, OrderStatus.IN_PROGRESS, OrderStatus.PAUSED)


def _pct(part: float, whole: float) -> float:
    return round(part / whole * 100, 2) if whole else 0.0


def build(db: Session, date_from: date | None = None, date_to: date | None = None, plant_id: int | None = None) -> dict:
    start, end = default_window(date_from, date_to)
    now = utcnow()
    window_minutes = max((end - start).total_seconds() / 60.0, 1.0)

    line_ids = select(ProductionLine.id).where(ProductionLine.plant_id == plant_id) if plant_id is not None else None
    batch_ids = select(ProductionBatch.id).where(ProductionBatch.line_id.in_(line_ids)) if line_ids is not None else None

    # ---- orders (all time)
    q = select(ProductionOrder.status, func.count()).where(ProductionOrder.is_deleted.is_(False))
    if line_ids is not None:
        q = q.where(ProductionOrder.line_id.in_(line_ids))
    by_status = {s.value: 0 for s in OrderStatus}
    for status, count in db.execute(q.group_by(ProductionOrder.status)).all():
        by_status[status.value] = count
    orders = {
        "total": sum(by_status.values()),
        "active": sum(by_status[s.value] for s in ACTIVE_STATES),
        "completed": by_status[OrderStatus.COMPLETED.value],
        "by_status": by_status,
    }

    # ---- production
    def produced_since(since) -> int:
        q = select(func.coalesce(func.sum(ProductionOutputLog.produced), 0)).where(ProductionOutputLog.recorded_at >= since)
        if batch_ids is not None:
            q = q.where(ProductionOutputLog.batch_id.in_(batch_ids))
        return int(db.scalar(q) or 0)

    q = select(func.coalesce(func.sum(ProductionOutputLog.produced), 0), func.coalesce(func.sum(ProductionOutputLog.rejected), 0)).where(
        ProductionOutputLog.recorded_at >= start, ProductionOutputLog.recorded_at < end)
    if batch_ids is not None:
        q = q.where(ProductionOutputLog.batch_id.in_(batch_ids))
    produced_w, rejected_w = db.execute(q).one()

    bq = select(ProductionBatch).where(
        ProductionBatch.is_deleted.is_(False), ProductionBatch.status != BatchStatus.CANCELLED,
        ProductionBatch.start_time.is_not(None), ProductionBatch.start_time >= start, ProductionBatch.start_time < end,
        ProductionBatch.produced_quantity > 0)
    if line_ids is not None:
        bq = bq.where(ProductionBatch.line_id.in_(line_ids))
    effs = [b.efficiency for b in db.scalars(bq).all()]
    production = {
        "daily_production": produced_since(day_start(now.date())),
        "monthly_production": produced_since(day_start(now.date().replace(day=1))),
        "production_efficiency_percent": round(sum(effs) / len(effs), 2) if effs else 0.0,
        "rejection_rate_percent": _pct(rejected_w, produced_w + rejected_w),
    }

    # ---- machines
    mq = select(Machine).where(Machine.is_deleted.is_(False))
    if line_ids is not None:
        mq = mq.where(Machine.line_id.in_(line_ids))
    machines = db.scalars(mq).all()
    machine_status = {s.value: 0 for s in MachineStatus}
    for m in machines:
        machine_status[m.status.value] += 1
    in_service = [m for m in machines if m.status != MachineStatus.DECOMMISSIONED]
    ids = [m.id for m in in_service]
    capacity = window_minutes * len(ids)
    run_minutes = 0.0
    if ids:
        for b in db.scalars(select(ProductionBatch).where(
                ProductionBatch.machine_id.in_(ids), ProductionBatch.start_time.is_not(None), ProductionBatch.start_time < end,
                (ProductionBatch.end_time.is_(None)) | (ProductionBatch.end_time > start))).all():
            run_minutes += overlap_minutes(b.start_time, b.end_time, start, end)
    downtime = sum(downtime_service.downtime_minutes_by_machine(db, ids, start, end).values())
    machine_stats = {
        "machine_utilization_percent": min(_pct(run_minutes, capacity), 100.0),
        "machine_downtime_percent": min(_pct(downtime, capacity), 100.0),
        "by_status": machine_status,
    }

    # ---- quality
    iq = select(Inspection.result, func.count()).where(Inspection.inspection_date >= start, Inspection.inspection_date < end)
    if batch_ids is not None:
        iq = iq.where(Inspection.batch_id.in_(batch_ids))
    results = {r.value: c for r, c in db.execute(iq.group_by(Inspection.result)).all()}
    passed, failed = results.get(InspectionResult.PASS.value, 0), results.get(InspectionResult.FAIL.value, 0)
    quality = {"total_inspections": passed + failed, "passed": passed, "failed": failed,
               "quality_pass_percent": _pct(passed, passed + failed)}

    # ---- materials
    cq = (select(Material.code, Material.name, Material.unit, func.sum(-InventoryTransaction.delta).label("qty"))
          .join(Material, Material.id == InventoryTransaction.material_id)
          .where(InventoryTransaction.movement_type == MovementType.CONSUMPTION,
                 InventoryTransaction.created_at >= start, InventoryTransaction.created_at < end))
    if batch_ids is not None:
        cq = cq.where(InventoryTransaction.batch_id.in_(batch_ids))
    consumption = [{"material_code": c, "material_name": n, "unit": u, "consumed_quantity": round(q or 0, 3)}
                   for c, n, u, q in db.execute(cq.group_by(Material.code, Material.name, Material.unit).order_by(func.sum(-InventoryTransaction.delta).desc())).all()]
    low_stock = [{"material_id": m.id, "code": m.code, "name": m.name, "unit": m.unit, "available_quantity": m.available_quantity,
                  "minimum_stock_level": m.minimum_stock_level, "reorder_level": m.reorder_level}
                 for m in material_service.low_stock(db)]

    # ---- defects
    dq = select(Defect).where(Defect.is_deleted.is_(False), Defect.created_at >= start, Defect.created_at < end)
    if batch_ids is not None:
        dq = dq.where(Defect.batch_id.in_(batch_ids))
    defects = db.scalars(dq).all()
    by_severity = {s.value: 0 for s in Severity}
    by_res = {s.value: 0 for s in ResolutionStatus}
    for d in defects:
        by_severity[d.severity.value] += 1
        by_res[d.resolution_status.value] += 1

    return {
        "window_start": start.date(),
        "window_end": (end - timedelta(seconds=1)).date(),
        "orders": orders,
        "production": production,
        "machines": machine_stats,
        "quality": quality,
        "materials": {"consumption": consumption, "low_stock": low_stock},
        "maintenance_due": maintenance_service.maintenance_due(db, settings.MAINTENANCE_DUE_WARNING_DAYS, plant_id),
        "defects": {
            "total": len(defects),
            "open": by_res[ResolutionStatus.OPEN.value] + by_res[ResolutionStatus.IN_PROGRESS.value],
            "by_severity": by_severity, "by_status": by_res,
        },
    }
