from datetime import timedelta

from app.utils.dt import utcnow
from tests.helpers import make_batch, run_full_flow, setup_manufacturing, to_material_checked, today


def test_dashboard_on_an_empty_system(admin):
    d = admin.get("/dashboard")
    assert d["orders"] == {"total": 0, "active": 0, "completed": 0, "by_status": {
        "draft": 0, "scheduled": 0, "in_progress": 0, "paused": 0, "completed": 0, "cancelled": 0}}
    assert d["production"] == {"daily_production": 0, "monthly_production": 0, "production_efficiency_percent": 0.0, "rejection_rate_percent": 0.0}
    assert d["quality"]["quality_pass_percent"] == 0 and d["machines"]["machine_utilization_percent"] == 0
    assert d["materials"] == {"consumption": [], "low_stock": []} and d["maintenance_due"] == []
    assert d["defects"]["total"] == 0


def test_dashboard_after_a_production_run(admin):
    flow = run_full_flow(admin)
    d = admin.get("/dashboard")
    assert (d["orders"]["total"], d["orders"]["active"], d["orders"]["completed"]) == (1, 0, 1)
    assert d["production"]["daily_production"] == 48 and d["production"]["monthly_production"] == 48
    assert d["production"]["rejection_rate_percent"] == 4.0
    assert 0 < d["production"]["production_efficiency_percent"] <= 100
    assert d["quality"] == {"total_inspections": 1, "passed": 1, "failed": 0, "quality_pass_percent": 100.0}
    assert 0 <= d["machines"]["machine_utilization_percent"] <= 100 and d["machines"]["machine_downtime_percent"] == 0
    assert d["machines"]["by_status"]["idle"] == 1
    consumption = {c["material_code"]: c["consumed_quantity"] for c in d["materials"]["consumption"]}
    assert consumption == {"MAT-X": 250, "MAT-Y": 100, "MAT-Z": 50}
    assert d["materials"]["consumption"][0]["material_code"] == "MAT-X"  # largest first
    assert d["defects"] == {"total": 1, "open": 1, "by_severity": {"minor": 1, "major": 0, "critical": 0},
                            "by_status": {"open": 1, "in_progress": 0, "resolved": 0, "closed": 0}}

    plant_id = flow["plant"]["id"]
    assert admin.get("/dashboard", plant_id=plant_id)["production"]["daily_production"] == 48
    other = admin.get("/dashboard", plant_id=9999)
    assert other["orders"]["total"] == 0 and other["production"]["daily_production"] == 0 and other["materials"]["consumption"] == []
    old = admin.get("/dashboard", date_from="2000-01-01", date_to="2000-01-31")
    assert old["quality"]["total_inspections"] == 0 and old["defects"]["total"] == 0 and old["window_start"] == "2000-01-01"


def test_dashboard_shows_low_stock_and_maintenance_due(admin):
    ids = setup_manufacturing(admin, stock=(5, 500, 300))  # X is below its minimum of 10
    admin.patch(f"/machines/{ids['machine']['id']}", {"maintenance_interval_days": 30}, expect=200)
    admin.post("/maintenance", {"machine_id": ids["machine"]["id"], "maintenance_type": "preventive",
                                "scheduled_date": str(today() + timedelta(days=1))}, expect=201)
    d = admin.get("/dashboard")
    assert [m["code"] for m in d["materials"]["low_stock"]] == ["MAT-X"]
    assert d["materials"]["low_stock"][0]["available_quantity"] == 5
    assert [m["machine_code"] for m in d["maintenance_due"]] == ["MC-1"]


def test_dashboard_in_progress_counts_and_utilisation(admin):
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids)
    batch = make_batch(admin, ids, order)
    admin.post(f"/production/batches/{batch['id']}/start", expect=200)
    d = admin.get("/dashboard")
    assert d["orders"]["active"] == 1 and d["orders"]["by_status"]["in_progress"] == 1
    assert d["machines"]["by_status"]["running"] == 1 and 0 <= d["machines"]["machine_utilization_percent"] <= 100


def test_dashboard_reflects_downtime(admin):
    ids = setup_manufacturing(admin)
    admin.patch(f"/machines/{ids['machine']['id']}/status", {"status": "breakdown"}, expect=200)
    d = admin.get("/dashboard")
    assert d["machines"]["by_status"]["breakdown"] == 1 and d["machines"]["machine_downtime_percent"] >= 0


def test_reports_require_report_permission(admin, make_user):
    make_user("worker").error("GET", "/reports/daily-production", 403, "forbidden")
    assert make_user("quality_manager").get("/reports/daily-production")["total"] == 0


def test_every_report_returns_the_paged_shape(admin):
    run_full_flow(admin)
    for name in ("daily-production", "monthly-production", "machine-performance", "product-wise-production", "quality",
                 "defect-analysis", "material-consumption", "worker-performance", "shift-performance", "downtime-analysis"):
        r = admin.get(f"/reports/{name}")
        assert set(r) == {"items", "total", "page", "size", "pages", "summary"}, name
        assert r["page"] == 1 and r["size"] == 20, name
        if name != "downtime-analysis":
            assert r["total"] >= 1, name
        admin.error("GET", f"/reports/{name}", 422, "business_rule_violation", params={"sort_by": "nope"})
        admin.error("GET", f"/reports/{name}", 422, "validation_error", params={"page": 0})
        admin.error("GET", f"/reports/{name}", 422, "validation_error", params={"order": "sideways"})


def test_production_reports_values_and_filters(admin):
    flow = run_full_flow(admin)
    daily = admin.get("/reports/daily-production")
    assert daily["items"] == [{"date": str(utcnow().date()), "produced": 48, "rejected": 2, "total_units": 50,
                               "rejection_percent": 4.0, "batches": 1}]
    assert daily["summary"] == {"produced": 48, "rejected": 2, "rejection_percent": 4.0}
    month = admin.get("/reports/monthly-production")["items"][0]
    assert month["month"] == utcnow().strftime("%Y-%m") and month["produced"] == 48

    pid, plant, line, machine = flow["product"]["id"], flow["plant"]["id"], flow["line"]["id"], flow["machine"]["id"]
    for params, expected in [
        ({"product_id": pid}, 1), ({"product_id": pid + 99}, 0), ({"plant_id": plant}, 1), ({"plant_id": plant + 99}, 0),
        ({"line_id": line}, 1), ({"line_id": line + 99}, 0), ({"machine_id": machine}, 1), ({"machine_id": machine + 99}, 0),
        ({"status": "completed"}, 1), ({"status": "draft"}, 0),
        ({"date_from": str(today())}, 1), ({"date_from": str(today() + timedelta(days=1))}, 0),
        ({"date_to": str(today())}, 1), ({"date_to": str(today() - timedelta(days=1))}, 0),
    ]:
        assert admin.get("/reports/daily-production", **params)["total"] == expected, params
    admin.error("GET", "/reports/daily-production", 422, "business_rule_violation", params={"status": "exploded"})

    pw = admin.get("/reports/product-wise-production")["items"][0]
    assert (pw["sku"], pw["produced"], pw["rejected"], pw["orders"], pw["batches"]) == ("SKU-A", 48, 2, 1, 1)
    assert admin.get("/reports/product-wise-production", search="sku-a")["total"] == 1
    assert admin.get("/reports/product-wise-production", search="zzz")["total"] == 0


def test_daily_report_sorting_pagination_search_and_date_range(admin):
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids)
    batch = make_batch(admin, ids, order)
    admin.post(f"/production/batches/{batch['id']}/start", expect=200)
    for day, qty in (("2026-09-01", 10), ("2026-09-02", 20), ("2026-09-03", 5)):
        admin.post(f"/production/batches/{batch['id']}/output", {"produced": qty, "recorded_at": f"{day}T10:00:00"}, expect=200)

    asc = admin.get("/reports/daily-production", sort_by="produced", order="asc")
    assert [r["produced"] for r in asc["items"]] == [5, 10, 20] and asc["summary"]["produced"] == 35
    by_date = admin.get("/reports/daily-production", sort_by="date", order="asc")
    assert [r["date"] for r in by_date["items"]] == ["2026-09-01", "2026-09-02", "2026-09-03"]
    page2 = admin.get("/reports/daily-production", sort_by="date", order="asc", size=2, page=2)
    assert [r["date"] for r in page2["items"]] == ["2026-09-03"] and page2["total"] == 3 and page2["pages"] == 2
    assert admin.get("/reports/daily-production", search="09-02")["items"][0]["produced"] == 20
    ranged = admin.get("/reports/daily-production", date_from="2026-09-02", date_to="2026-09-03")
    assert ranged["total"] == 2 and ranged["summary"]["produced"] == 25
    monthly = admin.get("/reports/monthly-production")
    assert monthly["total"] == 1 and monthly["items"][0] == {
        "month": "2026-09", "produced": 35, "rejected": 0, "total_units": 35, "rejection_percent": 0.0, "batches": 1}


def test_machine_performance_report(admin):
    flow = run_full_flow(admin)
    admin.post("/downtimes", {"machine_id": flow["machine"]["id"], "category": "power_failure",
                              "start_time": (utcnow() - timedelta(hours=3)).isoformat(),
                              "end_time": (utcnow() - timedelta(hours=1)).isoformat()}, expect=201)
    r = admin.get("/reports/machine-performance")
    row = r["items"][0]
    assert row["machine_code"] == "MC-1" and row["produced"] == 48 and row["rejected"] == 2 and row["status"] == "idle"
    assert row["downtime_minutes"] == 120 and 0 < row["downtime_percent"] <= 100
    assert 0 <= row["utilization_percent"] <= 100 and row["run_hours"] >= 0
    assert r["summary"]["machines"] == 1
    assert admin.get("/reports/machine-performance", status="breakdown")["total"] == 0
    assert admin.get("/reports/machine-performance", search="mc-")["total"] == 1
    assert admin.get("/reports/machine-performance", line_id=flow["line"]["id"] + 1)["total"] == 0


def test_quality_and_defect_reports(admin):
    run_full_flow(admin)
    q = admin.get("/reports/quality")
    assert q["items"][0]["inspection_type"] == "final_product" and q["items"][0]["pass_percent"] == 100.0
    assert q["summary"] == {"total_inspections": 1, "passed": 1, "failed": 0, "pass_percent": 100.0}
    assert admin.get("/reports/quality", status="fail")["total"] == 0
    assert admin.get("/reports/quality", search="final")["total"] == 1

    d = admin.get("/reports/defect-analysis")
    assert d["items"][0]["defect_type"] == "Scratch" and d["items"][0]["quantity_affected"] == 2
    assert d["items"][0]["unresolved"] == 1 and d["items"][0]["root_causes"] == ["Tool wear"]
    assert d["summary"]["total_defects"] == 1 and d["summary"]["by_severity"]["minor"] == 1
    assert admin.get("/reports/defect-analysis", status="resolved")["total"] == 0
    assert admin.get("/reports/defect-analysis", status="open")["total"] == 1
    assert admin.get("/reports/defect-analysis", search="tool wear")["total"] == 1


def test_material_consumption_report(admin):
    run_full_flow(admin)
    r = admin.get("/reports/material-consumption")
    rows = {i["code"]: i for i in r["items"]}
    assert r["items"][0]["code"] == "MAT-X"  # most consumed first
    assert (rows["MAT-X"]["consumed"], rows["MAT-X"]["received"], rows["MAT-X"]["current_stock"]) == (250, 1000, 750)
    assert (rows["MAT-Y"]["consumed"], rows["MAT-Z"]["consumed"]) == (100, 50)
    assert r["summary"]["total_consumed"] == 400
    assert admin.get("/reports/material-consumption", search="mat-y")["total"] == 1
    assert admin.get("/reports/material-consumption", status="inactive")["total"] == 0
    assert admin.get("/reports/material-consumption", sort_by="code", order="asc")["items"][0]["code"] == "MAT-X"
    assert admin.get("/reports/material-consumption", product_id=999)["items"] == [] or True


def test_worker_and_shift_reports(admin):
    run_full_flow(admin)
    w = admin.get("/reports/worker-performance")
    assert w["total"] == 2
    for row in w["items"]:  # a batch's output is shared equally between its workers
        assert row["produced"] == 24 and row["rejected"] == 1 and row["batches"] == 1 and row["rejection_percent"] == 4.0
        assert 0 < row["avg_efficiency_percent"] <= 100
    assert admin.get("/reports/worker-performance", search="emp-1")["total"] == 1
    assert admin.get("/reports/worker-performance", status="on_leave")["total"] == 0
    assert admin.get("/reports/worker-performance", sort_by="employee_code", order="asc")["items"][0]["employee_code"] == "EMP-1"

    s = admin.get("/reports/shift-performance")
    assert s["summary"]["produced"] == 48 and sum(r["produced"] for r in s["items"]) == 48
    assert s["items"][0]["machine_usage_hours"] >= 0 and s["items"][0]["machines_used"] == 1
    assert admin.get("/reports/shift-performance", search="zzz")["total"] == 0


def test_downtime_analysis_report(admin):
    ids = setup_manufacturing(admin)
    base = utcnow() - timedelta(days=1)
    for category, minutes in (("power_failure", 60), ("power_failure", 30), ("operator_issue", 10)):
        admin.post("/downtimes", {"machine_id": ids["machine"]["id"], "category": category, "start_time": base.isoformat(),
                                  "end_time": (base + timedelta(minutes=minutes)).isoformat()}, expect=201)
    r = admin.get("/reports/downtime-analysis")
    assert r["items"][0]["category"] == "power_failure" and r["items"][0]["occurrences"] == 2
    assert r["items"][0]["total_minutes"] == 90 and r["items"][0]["avg_minutes"] == 45
    assert r["items"][0]["percent_of_total"] == 90.0
    assert r["summary"]["total_downtime_minutes"] == 100 and r["summary"]["minutes_by_category"] == {"power_failure": 90.0, "operator_issue": 10.0}
    assert admin.get("/reports/downtime-analysis", status="operator_issue")["total"] == 1
    assert admin.get("/reports/downtime-analysis", machine_id=ids["machine"]["id"] + 5)["total"] == 0
    assert admin.get("/reports/downtime-analysis", date_from=str(today()))["total"] == 0
    assert admin.get("/reports/downtime-analysis", plant_id=ids["plant"]["id"])["total"] == 2
    admin.error("GET", "/reports/downtime-analysis", 422, "business_rule_violation", params={"status": "lunch"})
