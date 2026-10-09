"""Advanced reports (Level 19).

Every report accepts the same filters (see app/schemas/report.py): date range, plant, product, machine,
production line, status, search, sorting and pagination. Date filters are inclusive; with no dates the
report covers all time (machine performance and downtime % default to the last 30 days because they
are rates over a window). Rows are aggregated in Python from filtered SQL so the logic stays readable.
"""
from collections import defaultdict
from enum import Enum
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.exceptions import BusinessRuleError
from app.models.inventory import InventoryTransaction
from app.models.machine import Machine
from app.models.maintenance import Downtime, MaintenanceRecord
from app.models.material import Material
from app.models.plant import ProductionLine
from app.models.product import Product
from app.models.production import ProductionBatch, ProductionOrder, ProductionOutputLog
from app.models.quality import Defect, Inspection
from app.models.worker import Shift, Worker
from app.schemas.report import ReportFilters
from app.services import downtime_service
from app.utils.dt import day_end_exclusive, day_start, default_window, overlap_minutes, utcnow
from app.utils.enums import (
    BatchStatus, DowntimeCategory, InspectionResult, MachineStatus, MaintenanceStatus, MaterialStatus,
    MovementType, OrderStatus, ResolutionStatus, Severity, WorkerStatus,
)
from app.utils.pagination import paginate_list, sort_rows


# ---------------------------------------------------------------- helpers
def _pct(part: float, whole: float) -> float:
    return round(part / whole * 100, 2) if whole else 0.0


def _enum(enum_cls: type[Enum], value: str | None):
    if value is None:
        return None
    try:
        return enum_cls(value.lower())
    except ValueError:
        raise BusinessRuleError(f"Invalid status '{value}'. Allowed: {', '.join(m.value for m in enum_cls)}")


def _bounds(f: ReportFilters):
    return (day_start(f.date_from) if f.date_from else None, day_end_exclusive(f.date_to) if f.date_to else None)


def _between(stmt, column, f: ReportFilters):
    start, end = _bounds(f)
    if start is not None:
        stmt = stmt.where(column >= start)
    if end is not None:
        stmt = stmt.where(column < end)
    return stmt


def _finish(rows: list[dict], f: ReportFilters, *, allowed: set[str], default_sort: str, search_keys: list[str],
            summarize: Callable[[list[dict]], dict] | None = None) -> dict:
    if f.search:
        term = f.search.strip().lower()
        rows = [r for r in rows if any(term in str(r.get(k, "")).lower() for k in search_keys)]
    rows = sort_rows(rows, f.sort_by, f.order, allowed, default_sort)
    page = paginate_list(rows, f.page, f.size)
    page["summary"] = summarize(rows) if summarize else None
    return page


def _output_rows(db: Session, f: ReportFilters):
    """Output-log rows joined to batch / order / line, with all common filters applied."""
    stmt = (select(
        ProductionOutputLog.recorded_at.label("recorded_at"), ProductionOutputLog.produced.label("produced"),
        ProductionOutputLog.rejected.label("rejected"), ProductionOutputLog.batch_id.label("batch_id"),
        ProductionOutputLog.shift_id.label("shift_id"), ProductionBatch.machine_id.label("machine_id"),
        ProductionBatch.line_id.label("line_id"), ProductionBatch.order_id.label("order_id"),
        ProductionOrder.product_id.label("product_id"), ProductionLine.plant_id.label("plant_id"))
        .join(ProductionBatch, ProductionBatch.id == ProductionOutputLog.batch_id)
        .join(ProductionOrder, ProductionOrder.id == ProductionBatch.order_id)
        .join(ProductionLine, ProductionLine.id == ProductionBatch.line_id))
    stmt = _between(stmt, ProductionOutputLog.recorded_at, f)
    if f.plant_id is not None:
        stmt = stmt.where(ProductionLine.plant_id == f.plant_id)
    if f.product_id is not None:
        stmt = stmt.where(ProductionOrder.product_id == f.product_id)
    if f.machine_id is not None:
        stmt = stmt.where(ProductionBatch.machine_id == f.machine_id)
    if f.line_id is not None:
        stmt = stmt.where(ProductionBatch.line_id == f.line_id)
    if f.status:
        stmt = stmt.where(ProductionOrder.status == _enum(OrderStatus, f.status))
    return db.execute(stmt).all()


def _batches(db: Session, f: ReportFilters) -> list[ProductionBatch]:
    """Started, non-cancelled batches matching the common filters (date applies to start_time)."""
    stmt = (select(ProductionBatch)
            .join(ProductionOrder, ProductionOrder.id == ProductionBatch.order_id)
            .join(ProductionLine, ProductionLine.id == ProductionBatch.line_id)
            .where(ProductionBatch.is_deleted.is_(False), ProductionBatch.status != BatchStatus.CANCELLED,
                   ProductionBatch.start_time.is_not(None))
            .options(selectinload(ProductionBatch.workers),
                     joinedload(ProductionBatch.order).joinedload(ProductionOrder.product)))
    stmt = _between(stmt, ProductionBatch.start_time, f)
    if f.plant_id is not None:
        stmt = stmt.where(ProductionLine.plant_id == f.plant_id)
    if f.product_id is not None:
        stmt = stmt.where(ProductionOrder.product_id == f.product_id)
    if f.machine_id is not None:
        stmt = stmt.where(ProductionBatch.machine_id == f.machine_id)
    if f.line_id is not None:
        stmt = stmt.where(ProductionBatch.line_id == f.line_id)
    return list(db.scalars(stmt).all())


def _production_summary(rows: list[dict]) -> dict:
    produced, rejected = sum(r["produced"] for r in rows), sum(r["rejected"] for r in rows)
    return {"produced": produced, "rejected": rejected, "rejection_percent": _pct(rejected, produced + rejected)}


def _group_production(db: Session, f: ReportFilters, key_fn: Callable) -> dict:
    groups: dict[Any, dict] = defaultdict(lambda: {"produced": 0, "rejected": 0, "batches": set()})
    for r in _output_rows(db, f):
        g = groups[key_fn(r)]
        g["produced"] += r.produced
        g["rejected"] += r.rejected
        g["batches"].add(r.batch_id)
    return groups


_PROD_FIELDS = {"produced", "rejected", "total_units", "rejection_percent", "batches"}


def _prod_row(label: dict, g: dict) -> dict:
    return {**label, "produced": g["produced"], "rejected": g["rejected"], "total_units": g["produced"] + g["rejected"],
            "rejection_percent": _pct(g["rejected"], g["produced"] + g["rejected"]), "batches": len(g["batches"])}


# ---------------------------------------------------------------- 1. daily production
def daily_production(db: Session, f: ReportFilters) -> dict:
    groups = _group_production(db, f, lambda r: r.recorded_at.date().isoformat())
    rows = [_prod_row({"date": k}, g) for k, g in groups.items()]
    return _finish(rows, f, allowed=_PROD_FIELDS | {"date"}, default_sort="date", search_keys=["date"], summarize=_production_summary)


# ---------------------------------------------------------------- 2. monthly production
def monthly_production(db: Session, f: ReportFilters) -> dict:
    groups = _group_production(db, f, lambda r: f"{r.recorded_at.year}-{r.recorded_at.month:02d}")
    rows = [_prod_row({"month": k}, g) for k, g in groups.items()]
    return _finish(rows, f, allowed=_PROD_FIELDS | {"month"}, default_sort="month", search_keys=["month"], summarize=_production_summary)


# ---------------------------------------------------------------- 3. machine performance
def machine_performance(db: Session, f: ReportFilters) -> dict:
    start, end = default_window(f.date_from, f.date_to)
    window = max((end - start).total_seconds() / 60.0, 1.0)

    mq = select(Machine).where(Machine.is_deleted.is_(False))
    if f.machine_id is not None:
        mq = mq.where(Machine.id == f.machine_id)
    if f.line_id is not None:
        mq = mq.where(Machine.line_id == f.line_id)
    if f.plant_id is not None:
        mq = mq.where(Machine.line_id.in_(select(ProductionLine.id).where(ProductionLine.plant_id == f.plant_id)))
    if f.status:
        mq = mq.where(Machine.status == _enum(MachineStatus, f.status))
    machines = list(db.scalars(mq).all())
    ids = [m.id for m in machines]

    bq = (select(ProductionBatch).join(ProductionOrder, ProductionOrder.id == ProductionBatch.order_id)
          .where(ProductionBatch.machine_id.in_(ids or [-1]), ProductionBatch.is_deleted.is_(False),
                 ProductionBatch.start_time.is_not(None), ProductionBatch.start_time < end,
                 (ProductionBatch.end_time.is_(None)) | (ProductionBatch.end_time > start)))
    if f.product_id is not None:
        bq = bq.where(ProductionOrder.product_id == f.product_id)
    batches = list(db.scalars(bq).all())
    run_minutes: dict[int, float] = defaultdict(float)
    batch_machine = {}
    for b in batches:
        run_minutes[b.machine_id] += overlap_minutes(b.start_time, b.end_time, start, end)
        batch_machine[b.id] = b.machine_id

    produced: dict[int, int] = defaultdict(int)
    rejected: dict[int, int] = defaultdict(int)
    if batch_machine:
        for log in db.scalars(select(ProductionOutputLog).where(
                ProductionOutputLog.batch_id.in_(list(batch_machine)),
                ProductionOutputLog.recorded_at >= start, ProductionOutputLog.recorded_at < end)).all():
            produced[batch_machine[log.batch_id]] += log.produced
            rejected[batch_machine[log.batch_id]] += log.rejected

    down = downtime_service.downtime_minutes_by_machine(db, ids, start, end)
    maint_count: dict[int, int] = defaultdict(int)
    maint_cost: dict[int, float] = defaultdict(float)
    if ids:
        for rec in db.scalars(select(MaintenanceRecord).where(
                MaintenanceRecord.machine_id.in_(ids), MaintenanceRecord.status == MaintenanceStatus.COMPLETED,
                MaintenanceRecord.completed_at >= start, MaintenanceRecord.completed_at < end)).all():
            maint_count[rec.machine_id] += 1
            maint_cost[rec.machine_id] += rec.total_cost

    rows = []
    for m in machines:
        rows.append({
            "machine_id": m.id, "machine_code": m.machine_code, "name": m.name, "machine_type": m.machine_type,
            "status": m.status.value, "produced": produced[m.id], "rejected": rejected[m.id],
            "rejection_percent": _pct(rejected[m.id], produced[m.id] + rejected[m.id]),
            "run_hours": round(run_minutes[m.id] / 60.0, 2),
            "utilization_percent": min(_pct(run_minutes[m.id], window), 100.0),
            "downtime_minutes": round(down.get(m.id, 0.0), 2),
            "downtime_percent": min(_pct(down.get(m.id, 0.0), window), 100.0),
            "maintenance_count": maint_count[m.id], "maintenance_cost": round(maint_cost[m.id], 2),
        })

    def summarize(rs):
        n = len(rs) or 1
        return {"window_start": start, "window_end": end, "machines": len(rs),
                "avg_utilization_percent": round(sum(r["utilization_percent"] for r in rs) / n, 2),
                "avg_downtime_percent": round(sum(r["downtime_percent"] for r in rs) / n, 2),
                "total_maintenance_cost": round(sum(r["maintenance_cost"] for r in rs), 2)}

    allowed = {"machine_code", "name", "machine_type", "status", "produced", "rejected", "rejection_percent", "run_hours",
               "utilization_percent", "downtime_minutes", "downtime_percent", "maintenance_count", "maintenance_cost"}
    return _finish(rows, f, allowed=allowed, default_sort="utilization_percent",
                   search_keys=["machine_code", "name", "machine_type"], summarize=summarize)


# ---------------------------------------------------------------- 4. product-wise production
def product_wise_production(db: Session, f: ReportFilters) -> dict:
    out = list(_output_rows(db, f))
    groups: dict[int, dict] = defaultdict(lambda: {"produced": 0, "rejected": 0, "batches": set(), "orders": set()})
    for r in out:
        g = groups[r.product_id]
        g["produced"] += r.produced
        g["rejected"] += r.rejected
        g["batches"].add(r.batch_id)
        g["orders"].add(r.order_id)
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(list(groups) or [-1]))).all()}
    rows = [{**_prod_row({"product_id": pid, "sku": products[pid].sku, "name": products[pid].name}, g), "orders": len(g["orders"])}
            for pid, g in groups.items()]
    return _finish(rows, f, allowed=_PROD_FIELDS | {"sku", "name", "orders"}, default_sort="produced",
                   search_keys=["sku", "name"], summarize=_production_summary)


# ---------------------------------------------------------------- 5. quality report
def quality_report(db: Session, f: ReportFilters) -> dict:
    stmt = (select(Inspection.inspection_type, Inspection.result, ProductionOrder.product_id, Product.sku, Product.name)
            .join(ProductionBatch, ProductionBatch.id == Inspection.batch_id)
            .join(ProductionOrder, ProductionOrder.id == ProductionBatch.order_id)
            .join(Product, Product.id == ProductionOrder.product_id)
            .join(ProductionLine, ProductionLine.id == ProductionBatch.line_id))
    stmt = _between(stmt, Inspection.inspection_date, f)
    if f.plant_id is not None:
        stmt = stmt.where(ProductionLine.plant_id == f.plant_id)
    if f.product_id is not None:
        stmt = stmt.where(ProductionOrder.product_id == f.product_id)
    if f.machine_id is not None:
        stmt = stmt.where(ProductionBatch.machine_id == f.machine_id)
    if f.line_id is not None:
        stmt = stmt.where(ProductionBatch.line_id == f.line_id)
    if f.status:
        stmt = stmt.where(Inspection.result == _enum(InspectionResult, f.status))
    groups: dict[tuple, dict] = defaultdict(lambda: {"passed": 0, "failed": 0})
    for itype, result, pid, sku, name in db.execute(stmt).all():
        g = groups[(itype.value, pid, sku, name)]
        g["passed" if result == InspectionResult.PASS else "failed"] += 1
    rows = [{"inspection_type": t, "product_id": pid, "sku": sku, "name": name, "total": g["passed"] + g["failed"],
             "passed": g["passed"], "failed": g["failed"], "pass_percent": _pct(g["passed"], g["passed"] + g["failed"])}
            for (t, pid, sku, name), g in groups.items()]

    def summarize(rs):
        passed, total = sum(r["passed"] for r in rs), sum(r["total"] for r in rs)
        return {"total_inspections": total, "passed": passed, "failed": total - passed, "pass_percent": _pct(passed, total)}

    return _finish(rows, f, allowed={"inspection_type", "sku", "name", "total", "passed", "failed", "pass_percent"},
                   default_sort="total", search_keys=["inspection_type", "sku", "name"], summarize=summarize)


# ---------------------------------------------------------------- 6. defect analysis
def defect_analysis(db: Session, f: ReportFilters) -> dict:
    stmt = (select(Defect).join(ProductionBatch, ProductionBatch.id == Defect.batch_id)
            .join(ProductionLine, ProductionLine.id == ProductionBatch.line_id)
            .where(Defect.is_deleted.is_(False)))
    stmt = _between(stmt, Defect.created_at, f)
    if f.plant_id is not None:
        stmt = stmt.where(ProductionLine.plant_id == f.plant_id)
    if f.product_id is not None:
        stmt = stmt.where(Defect.product_id == f.product_id)
    if f.machine_id is not None:
        stmt = stmt.where(ProductionBatch.machine_id == f.machine_id)
    if f.line_id is not None:
        stmt = stmt.where(ProductionBatch.line_id == f.line_id)
    if f.status:
        stmt = stmt.where(Defect.resolution_status == _enum(ResolutionStatus, f.status))
    defects = list(db.scalars(stmt).all())

    groups: dict[tuple, dict] = defaultdict(lambda: {"occurrences": 0, "quantity_affected": 0, "unresolved": 0, "root_causes": set()})
    for d in defects:
        g = groups[(d.defect_type, d.severity.value)]
        g["occurrences"] += 1
        g["quantity_affected"] += d.quantity_affected
        g["unresolved"] += d.resolution_status in (ResolutionStatus.OPEN, ResolutionStatus.IN_PROGRESS)
        if d.root_cause:
            g["root_causes"].add(d.root_cause)
    rows = [{"defect_type": t, "severity": s, "occurrences": g["occurrences"], "quantity_affected": g["quantity_affected"],
             "unresolved": g["unresolved"], "root_causes": sorted(g["root_causes"])} for (t, s), g in groups.items()]

    def summarize(_rs):
        by_sev = {s.value: 0 for s in Severity}
        by_res = {s.value: 0 for s in ResolutionStatus}
        for d in defects:
            by_sev[d.severity.value] += 1
            by_res[d.resolution_status.value] += 1
        return {"total_defects": len(defects), "total_quantity_affected": sum(d.quantity_affected for d in defects),
                "by_severity": by_sev, "by_resolution_status": by_res}

    return _finish(rows, f, allowed={"defect_type", "severity", "occurrences", "quantity_affected", "unresolved"},
                   default_sort="occurrences", search_keys=["defect_type", "severity", "root_causes"], summarize=summarize)


# ---------------------------------------------------------------- 7. material consumption
def material_consumption(db: Session, f: ReportFilters) -> dict:
    stmt = (select(InventoryTransaction.material_id, InventoryTransaction.movement_type, InventoryTransaction.delta,
                   Material.code, Material.name, Material.unit, Material.available_quantity)
            .join(Material, Material.id == InventoryTransaction.material_id)
            .outerjoin(ProductionBatch, ProductionBatch.id == InventoryTransaction.batch_id)
            .outerjoin(ProductionOrder, ProductionOrder.id == ProductionBatch.order_id)
            .outerjoin(ProductionLine, ProductionLine.id == ProductionBatch.line_id)
            .where(InventoryTransaction.material_id.is_not(None)))
    stmt = _between(stmt, InventoryTransaction.created_at, f)
    if f.plant_id is not None:
        stmt = stmt.where(ProductionLine.plant_id == f.plant_id)
    if f.product_id is not None:
        stmt = stmt.where(ProductionOrder.product_id == f.product_id)
    if f.machine_id is not None:
        stmt = stmt.where(ProductionBatch.machine_id == f.machine_id)
    if f.line_id is not None:
        stmt = stmt.where(ProductionBatch.line_id == f.line_id)
    if f.status:
        stmt = stmt.where(Material.status == _enum(MaterialStatus, f.status))
    groups: dict[int, dict] = {}
    for mid, mtype, delta, code, name, unit, available in db.execute(stmt).all():
        g = groups.setdefault(mid, {"material_id": mid, "code": code, "name": name, "unit": unit, "consumed": 0.0,
                                    "received": 0.0, "issued_manually": 0.0, "adjusted_net": 0.0, "current_stock": available})
        if mtype == MovementType.CONSUMPTION:
            g["consumed"] += -delta
        elif mtype == MovementType.RECEIPT:
            g["received"] += delta
        elif mtype == MovementType.STOCK_OUT:
            g["issued_manually"] += -delta
        elif mtype == MovementType.ADJUSTMENT:
            g["adjusted_net"] += delta
    rows = [{**g, **{k: round(g[k], 3) for k in ("consumed", "received", "issued_manually", "adjusted_net")}} for g in groups.values()]
    return _finish(rows, f, allowed={"code", "name", "unit", "consumed", "received", "issued_manually", "adjusted_net", "current_stock"},
                   default_sort="consumed", search_keys=["code", "name"],
                   summarize=lambda rs: {"materials": len(rs), "total_consumed": round(sum(r["consumed"] for r in rs), 3),
                                         "total_received": round(sum(r["received"] for r in rs), 3)})


# ---------------------------------------------------------------- 8. worker performance
def worker_performance(db: Session, f: ReportFilters) -> dict:
    """A batch's output is shared equally between the workers assigned to it."""
    stats: dict[int, dict] = {}
    for b in _batches(db, f):
        if not b.workers:
            continue
        share = 1 / len(b.workers)
        for link in b.workers:
            s = stats.setdefault(link.worker_id, {"batches": 0, "produced": 0.0, "rejected": 0.0, "eff": []})
            s["batches"] += 1
            s["produced"] += b.produced_quantity * share
            s["rejected"] += b.rejected_quantity * share
            if b.produced_quantity:
                s["eff"].append(b.efficiency)
    wq = select(Worker).where(Worker.id.in_(list(stats) or [-1]))
    if f.status:
        wq = wq.where(Worker.status == _enum(WorkerStatus, f.status))
    rows = []
    for w in db.scalars(wq).all():
        s = stats[w.id]
        rows.append({"worker_id": w.id, "employee_code": w.employee_code, "full_name": w.full_name, "skill": w.skill,
                     "status": w.status.value, "batches": s["batches"], "produced": round(s["produced"], 2),
                     "rejected": round(s["rejected"], 2), "rejection_percent": _pct(s["rejected"], s["produced"] + s["rejected"]),
                     "avg_efficiency_percent": round(sum(s["eff"]) / len(s["eff"]), 2) if s["eff"] else 0.0})
    return _finish(rows, f, allowed={"employee_code", "full_name", "skill", "status", "batches", "produced", "rejected",
                                     "rejection_percent", "avg_efficiency_percent"},
                   default_sort="produced", search_keys=["employee_code", "full_name", "skill"],
                   summarize=lambda rs: {"workers": len(rs), "total_produced": round(sum(r["produced"] for r in rs), 2)})


# ---------------------------------------------------------------- 9. shift performance
def _shift_rows(db: Session, f: ReportFilters, only_shift_id: int | None = None) -> list[dict]:
    out_groups: dict[int | None, dict] = defaultdict(lambda: {"produced": 0, "rejected": 0, "batches": set()})
    for r in _output_rows(db, f):
        g = out_groups[r.shift_id]
        g["produced"] += r.produced
        g["rejected"] += r.rejected
        g["batches"].add(r.batch_id)
    usage: dict[int | None, dict] = defaultdict(lambda: {"minutes": 0.0, "machines": set(), "eff": []})
    for b in _batches(db, f):
        u = usage[b.shift_id]
        u["minutes"] += b.run_minutes
        if b.machine_id:
            u["machines"].add(b.machine_id)
        if b.produced_quantity:
            u["eff"].append(b.efficiency)
    shifts = {s.id: s for s in db.scalars(select(Shift)).all()}
    worker_counts: dict[int, int] = defaultdict(int)
    for sid in db.scalars(select(Worker.shift_id).where(Worker.is_deleted.is_(False), Worker.shift_id.is_not(None))).all():
        worker_counts[sid] += 1
    rows = []
    for sid in set(out_groups) | set(usage):
        if only_shift_id is not None and sid != only_shift_id:
            continue
        g, u, shift = out_groups[sid], usage[sid], shifts.get(sid)
        rows.append({
            "shift_id": sid, "shift_name": shift.name.value if shift else "unassigned",
            "start_time": shift.start_time.isoformat() if shift else None, "end_time": shift.end_time.isoformat() if shift else None,
            "workers": worker_counts.get(sid, 0), "produced": g["produced"], "rejected": g["rejected"],
            "rejection_percent": _pct(g["rejected"], g["produced"] + g["rejected"]), "batches": len(g["batches"]),
            "machines_used": len(u["machines"]), "machine_usage_hours": round(u["minutes"] / 60.0, 2),
            "avg_efficiency_percent": round(sum(u["eff"]) / len(u["eff"]), 2) if u["eff"] else 0.0,
        })
    return rows


def shift_performance(db: Session, f: ReportFilters) -> dict:
    return _finish(_shift_rows(db, f), f, allowed={"shift_name", "workers", "produced", "rejected", "rejection_percent", "batches",
                                                    "machines_used", "machine_usage_hours", "avg_efficiency_percent"},
                   default_sort="produced", search_keys=["shift_name"], summarize=_production_summary)


def single_shift_performance(db: Session, shift_id: int, f: ReportFilters) -> dict:
    rows = _shift_rows(db, f, only_shift_id=shift_id)
    shift = db.get(Shift, shift_id)
    return rows[0] if rows else {
        "shift_id": shift_id, "shift_name": shift.name.value if shift else None, "workers": 0, "produced": 0, "rejected": 0,
        "rejection_percent": 0.0, "batches": 0, "machines_used": 0, "machine_usage_hours": 0.0, "avg_efficiency_percent": 0.0}


# ---------------------------------------------------------------- 10. downtime analysis
def downtime_analysis(db: Session, f: ReportFilters) -> dict:
    stmt = (select(Downtime, Machine.machine_code, Machine.name)
            .join(Machine, Machine.id == Downtime.machine_id)
            .join(ProductionLine, ProductionLine.id == Machine.line_id))
    start, end = _bounds(f)
    if end is not None:
        stmt = stmt.where(Downtime.start_time < end)
    if start is not None:
        stmt = stmt.where((Downtime.end_time.is_(None)) | (Downtime.end_time > start))
    if f.plant_id is not None:
        stmt = stmt.where(ProductionLine.plant_id == f.plant_id)
    if f.machine_id is not None:
        stmt = stmt.where(Downtime.machine_id == f.machine_id)
    if f.line_id is not None:
        stmt = stmt.where(Machine.line_id == f.line_id)
    if f.status:  # for this report "status" is the downtime category
        stmt = stmt.where(Downtime.category == _enum(DowntimeCategory, f.status))
    window_start = start or day_start(utcnow().date().replace(year=2000))
    window_end = end or utcnow()
    groups: dict[tuple, dict] = defaultdict(lambda: {"occurrences": 0, "minutes": 0.0})
    for d, code, name in db.execute(stmt).all():
        g = groups[(d.category.value, d.machine_id, code, name)]
        g["occurrences"] += 1
        g["minutes"] += overlap_minutes(d.start_time, d.end_time, window_start, window_end)
    total = sum(g["minutes"] for g in groups.values())
    rows = [{"category": c, "machine_id": mid, "machine_code": code, "machine_name": name, "occurrences": g["occurrences"],
             "total_minutes": round(g["minutes"], 2), "avg_minutes": round(g["minutes"] / g["occurrences"], 2),
             "percent_of_total": _pct(g["minutes"], total)} for (c, mid, code, name), g in groups.items()]

    def summarize(rs):
        by_cat: dict[str, float] = defaultdict(float)
        for r in rs:
            by_cat[r["category"]] += r["total_minutes"]
        return {"total_downtime_minutes": round(sum(r["total_minutes"] for r in rs), 2),
                "occurrences": sum(r["occurrences"] for r in rs), "minutes_by_category": {k: round(v, 2) for k, v in by_cat.items()}}

    return _finish(rows, f, allowed={"category", "machine_code", "machine_name", "occurrences", "total_minutes", "avg_minutes", "percent_of_total"},
                   default_sort="total_minutes", search_keys=["category", "machine_code", "machine_name"], summarize=summarize)
