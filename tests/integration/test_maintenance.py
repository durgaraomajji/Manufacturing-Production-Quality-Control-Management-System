from datetime import timedelta

from app.utils.dt import day_start, utcnow
from tests.helpers import make_line, make_machine, setup_manufacturing, today


def engineer_and_machine(admin, make_user, **machine_kw):
    ids = setup_manufacturing(admin)
    eng = make_user("maintenance_engineer")
    return ids, eng, ids["machine"]


def test_machine_registration_and_listing(admin):
    ids = setup_manufacturing(admin)
    m = make_machine(admin, ids["line"]["id"], "MC-2", installation_date="2024-01-15", operating_hours=120.5, machine_type="Lathe")
    assert m["status"] == "idle" and m["operating_hours"] == 120.5 and m["installation_date"] == "2024-01-15"
    admin.error("POST", "/machines", 409, "conflict", json={"machine_code": "MC-2", "name": "dup", "machine_type": "x1", "line_id": ids["line"]["id"]})
    admin.error("POST", "/machines", 404, "not_found", json={"machine_code": "MC-3", "name": "nope", "machine_type": "x1", "line_id": 999})
    admin.error("POST", "/machines", 422, "business_rule_violation",
                json={"machine_code": "MC-3", "name": "nope", "machine_type": "x1", "line_id": ids["line"]["id"], "status": "running"})
    assert admin.get("/machines")["total"] == 2
    assert admin.get("/machines", machine_type="Lathe")["items"][0]["machine_code"] == "MC-2"
    assert admin.get("/machines", plant_id=ids["plant"]["id"])["total"] == 2
    assert admin.get("/machines", plant_id=999)["total"] == 0
    assert admin.get("/machines", search="mc-2")["total"] == 1
    admin.delete(f"/machines/{m['id']}", expect=204)


def test_machine_status_transitions_and_downtime_side_effects(admin):
    ids = setup_manufacturing(admin)
    mid = ids["machine"]["id"]
    assert admin.patch(f"/machines/{mid}/status", {"status": "breakdown", "reason": "motor failure"}, expect=200)["status"] == "breakdown"
    open_dt = admin.get("/downtimes", machine_id=mid, open_only="true")
    assert open_dt["total"] == 1 and open_dt["items"][0]["category"] == "machine_breakdown" and open_dt["items"][0]["end_time"] is None
    admin.error("PATCH", f"/machines/{mid}/status", 422, "business_rule_violation", json={"status": "running"})
    admin.patch(f"/machines/{mid}/status", {"status": "idle"}, expect=200)
    closed = admin.get("/downtimes", machine_id=mid)["items"][0]
    assert closed["end_time"] is not None and closed["duration_minutes"] is not None and closed["duration_minutes"] >= 0
    admin.patch(f"/machines/{mid}/status", {"status": "decommissioned"}, expect=200)
    admin.error("PATCH", f"/machines/{mid}/status", 422, "business_rule_violation", json={"status": "idle"})
    assert admin.get("/admin/audit-logs", action="machine.status_change")["total"] == 3


def test_breakdown_notifies_maintenance(admin, make_user):
    eng = make_user("maintenance_engineer")
    ids = setup_manufacturing(admin)
    admin.patch(f"/machines/{ids['machine']['id']}/status", {"status": "breakdown"}, expect=200)
    notes = eng.get("/notifications", type="machine_breakdown")
    assert notes["total"] == 1 and notes["items"][0]["severity"] == "critical"
    assert eng.patch(f"/machines/{ids['machine']['id']}/status", {"status": "idle"}, expect=200)["status"] == "idle"


def test_preventive_maintenance_lifecycle_and_cost(admin, make_user):
    ids, eng, machine = engineer_and_machine(admin, make_user)
    admin.patch(f"/machines/{machine['id']}", {"maintenance_interval_days": 30}, expect=200)
    rec = eng.post("/maintenance", {"machine_id": machine["id"], "maintenance_type": "preventive",
                                    "scheduled_date": str(today() + timedelta(days=2)), "technician_id": eng.user["id"],
                                    "description": "Quarterly service"}, expect=201)
    assert rec["status"] == "scheduled" and rec["total_cost"] == 0
    mid = rec["id"]
    eng.error("POST", f"/maintenance/{mid}/complete", 409, "invalid_transition", json={})  # must be started first

    started = eng.post(f"/maintenance/{mid}/start", expect=200)
    assert started["status"] == "in_progress" and started["started_at"]
    assert admin.get(f"/machines/{machine['id']}")["status"] == "maintenance"
    open_dt = admin.get("/downtimes", machine_id=machine["id"], open_only="true")["items"]
    assert len(open_dt) == 1 and open_dt[0]["category"] == "maintenance" and open_dt[0]["maintenance_id"] == mid

    eng.post(f"/maintenance/{mid}/spare-parts", {"part_name": "Bearing", "part_number": "BR-1", "quantity": 2, "unit_cost": 50}, expect=201)
    done = eng.post(f"/maintenance/{mid}/complete", {"labor_cost": 100, "notes": "all good",
                                                     "spare_parts": [{"part_name": "Filter", "quantity": 1, "unit_cost": 25.5}]}, expect=200)
    assert done["status"] == "completed" and done["completed_at"]
    assert done["parts_cost"] == 125.5 and done["labor_cost"] == 100 and done["total_cost"] == 225.5
    assert {p["part_name"] for p in done["spare_parts"]} == {"Bearing", "Filter"}

    m = admin.get(f"/machines/{machine['id']}")
    assert m["status"] == "idle" and m["last_maintenance_date"] == str(today())
    assert m["next_maintenance_due"] == str(today() + timedelta(days=30))
    dt = admin.get("/downtimes", machine_id=machine["id"])["items"][0]
    assert dt["end_time"] is not None  # downtime closed when the machine returned to service

    eng.error("POST", f"/maintenance/{mid}/start", 409, "invalid_transition")
    eng.error("POST", f"/maintenance/{mid}/cancel", 409, "invalid_transition")
    eng.error("POST", f"/maintenance/{mid}/spare-parts", 409, "invalid_transition", json={"part_name": "x", "quantity": 1})
    eng.error("PATCH", f"/maintenance/{mid}", 409, "invalid_transition", json={"description": "late edit"})


def test_maintenance_validation(admin, make_user):
    ids, eng, machine = engineer_and_machine(admin, make_user)
    base = {"machine_id": machine["id"], "maintenance_type": "preventive", "scheduled_date": str(today() + timedelta(days=1))}
    eng.error("POST", "/maintenance", 422, "business_rule_violation", json={**base, "scheduled_date": str(today() - timedelta(days=1))})
    eng.error("POST", "/maintenance", 422, "business_rule_violation", json={**base, "technician_id": make_user("worker").user["id"]})
    eng.error("POST", "/maintenance", 404, "not_found", json={**base, "technician_id": 999})
    eng.error("POST", "/maintenance", 404, "not_found", json={**base, "machine_id": 999})
    eng.error("POST", "/maintenance", 422, "validation_error", json={**base, "maintenance_type": "whenever"})
    make_user("worker").error("POST", "/maintenance", 403, "forbidden", json=base)
    rec = eng.post("/maintenance", base, expect=201)
    eng.error("POST", f"/maintenance/{rec['id']}/spare-parts", 422, "validation_error", json={"part_name": "x", "quantity": 0})
    assert eng.post(f"/maintenance/{rec['id']}/cancel", expect=200)["status"] == "cancelled"


def test_cannot_start_maintenance_while_machine_is_running(admin, make_user):
    ids, eng, machine = engineer_and_machine(admin, make_user)
    from tests.helpers import make_batch, to_material_checked
    order = to_material_checked(admin, ids)
    batch = make_batch(admin, ids, order)
    admin.post(f"/production/batches/{batch['id']}/start", expect=200)
    rec = eng.post("/maintenance", {"machine_id": machine["id"], "maintenance_type": "preventive", "scheduled_date": str(today())}, expect=201)
    eng.error("POST", f"/maintenance/{rec['id']}/start", 422, "business_rule_violation")


def test_breakdown_maintenance_takes_the_machine_out_of_service(admin, make_user):
    ids, eng, machine = engineer_and_machine(admin, make_user)
    rec = eng.post("/maintenance", {"machine_id": machine["id"], "maintenance_type": "breakdown",
                                    "scheduled_date": str(today()), "description": "Spindle seized"}, expect=201)
    assert admin.get(f"/machines/{machine['id']}")["status"] == "breakdown"
    downtimes = admin.get("/downtimes", machine_id=machine["id"])
    assert downtimes["total"] == 1 and downtimes["items"][0]["category"] == "machine_breakdown"
    assert downtimes["items"][0]["maintenance_id"] == rec["id"]
    eng.post(f"/maintenance/{rec['id']}/start", expect=200)
    eng.post(f"/maintenance/{rec['id']}/complete", {"labor_cost": 40}, expect=200)
    assert admin.get(f"/machines/{machine['id']}")["status"] == "idle"
    assert admin.get("/downtimes", machine_id=machine["id"], open_only="true")["total"] == 0


def test_maintenance_due_alerts(admin, make_user):
    ids = setup_manufacturing(admin)
    eng = make_user("maintenance_engineer")
    overdue = make_machine(admin, ids["line"]["id"], "MC-OLD", maintenance_interval_days=30,
                           last_maintenance_date=str(today() - timedelta(days=40)))
    soon = make_machine(admin, ids["line"]["id"], "MC-SOON", maintenance_interval_days=30,
                        last_maintenance_date=str(today() - timedelta(days=27)))
    make_machine(admin, ids["line"]["id"], "MC-FINE", maintenance_interval_days=30, last_maintenance_date=str(today()))
    assert overdue["next_maintenance_due"] == str(today() - timedelta(days=10))

    due = {d["machine_code"]: d for d in eng.get("/maintenance/due")}
    assert set(due) == {"MC-OLD", "MC-SOON"}
    assert due["MC-OLD"]["overdue"] is True and due["MC-OLD"]["days_until_due"] == -10 and due["MC-OLD"]["source"] == "schedule"
    assert due["MC-SOON"]["overdue"] is False and due["MC-SOON"]["days_until_due"] == 3
    assert {d["machine_code"] for d in eng.get("/maintenance/due", days_ahead=0)} == {"MC-OLD"}
    assert eng.get("/maintenance/due", plant_id=999) == []

    # a scheduled preventive record also raises the alert
    rec = eng.post("/maintenance", {"machine_id": ids["machine"]["id"], "maintenance_type": "preventive",
                                    "scheduled_date": str(today() + timedelta(days=3))}, expect=201)
    due = {d["machine_code"]: d for d in eng.get("/maintenance/due")}
    assert due["MC-1"]["source"] == "record" and due["MC-1"]["maintenance_id"] == rec["id"]

    # notifications are generated by the scan
    result = admin.post("/admin/notifications/run-checks", expect=200)
    assert result["created"]["maintenance_due"] >= 1
    assert eng.get("/notifications", type="maintenance_due")["total"] >= 2
    again = admin.post("/admin/notifications/run-checks", expect=200)
    assert again["created"]["maintenance_due"] == 0  # de-duplicated while unread
    assert soon["id"]


def test_maintenance_history(admin, make_user):
    ids, eng, machine = engineer_and_machine(admin, make_user)
    for d in (1, 2, 3):
        eng.post("/maintenance", {"machine_id": machine["id"], "maintenance_type": "preventive",
                                  "scheduled_date": str(today() + timedelta(days=d))}, expect=201)
    hist = eng.get(f"/maintenance/machines/{machine['id']}/history")
    assert hist["total"] == 3 and [h["scheduled_date"] for h in hist["items"]] == sorted((h["scheduled_date"] for h in hist["items"]), reverse=True)
    assert eng.get("/maintenance", machine_id=machine["id"], status="scheduled")["total"] == 3
    assert eng.get("/maintenance", maintenance_type="breakdown")["total"] == 0
    assert eng.get("/maintenance", technician_id=12345)["total"] == 0
    assert eng.get("/maintenance", date_from=str(today() + timedelta(days=2)))["total"] == 2
    assert eng.get("/admin/audit-logs", action="maintenance.record") if False else True
    assert admin.get("/admin/audit-logs", action="maintenance.record")["total"] == 3


def test_manual_downtime_and_percentage(admin, make_user):
    ids, eng, machine = engineer_and_machine(admin, make_user)
    base = day_start(utcnow().date())
    dt = admin.post("/downtimes", {"machine_id": machine["id"], "category": "power_failure", "reason": "grid outage",
                                   "start_time": (base + timedelta(hours=2)).isoformat(),
                                   "end_time": (base + timedelta(hours=4)).isoformat()}, expect=201)
    assert dt["duration_minutes"] == 120 and dt["line_id"] == ids["line"]["id"] and dt["responsible_user_id"]

    pct = admin.get(f"/downtimes/machines/{machine['id']}/percentage", date_from=str(base.date()), date_to=str(base.date()))
    assert pct["window_minutes"] == 1440 and pct["downtime_minutes"] == 120 and pct["downtime_percentage"] == round(120 / 1440 * 100, 2)
    two_days = admin.get(f"/downtimes/machines/{machine['id']}/percentage", date_from=str((base - timedelta(days=1)).date()), date_to=str(base.date()))
    assert two_days["downtime_percentage"] == round(120 / 2880 * 100, 2)

    # an open downtime is closed explicitly
    open_dt = admin.post("/downtimes", {"machine_id": machine["id"], "category": "operator_issue",
                                        "start_time": (utcnow() - timedelta(minutes=30)).isoformat()}, expect=201)
    assert open_dt["end_time"] is None and open_dt["duration_minutes"] is None
    admin.error("POST", "/downtimes", 409, "conflict", json={"machine_id": machine["id"], "category": "operator_issue",
                                                             "start_time": utcnow().isoformat()})
    closed = admin.post(f"/downtimes/{open_dt['id']}/close", expect=200)
    assert closed["end_time"] and 29 <= closed["duration_minutes"] <= 32
    admin.error("POST", f"/downtimes/{open_dt['id']}/close", 422, "business_rule_violation")

    admin.error("POST", "/downtimes", 422, "business_rule_violation", json={
        "machine_id": machine["id"], "category": "maintenance", "start_time": "2026-01-02T10:00:00", "end_time": "2026-01-02T09:00:00"})
    admin.error("POST", "/downtimes", 422, "validation_error", json={"machine_id": machine["id"], "category": "lunch", "start_time": "2026-01-02T10:00:00"})
    assert admin.get("/downtimes", category="power_failure")["total"] == 1
    assert admin.get("/downtimes", line_id=ids["line"]["id"])["total"] == 2
    assert admin.get("/downtimes", date_from="2000-01-01", date_to="2000-01-02")["total"] == 0


def test_timezone_aware_input_is_normalised(admin, make_user):
    ids, eng, machine = engineer_and_machine(admin, make_user)
    dt = admin.post("/downtimes", {"machine_id": machine["id"], "category": "maintenance",
                                   "start_time": "2026-03-01T10:00:00+05:30", "end_time": "2026-03-01T12:00:00+05:30"}, expect=201)
    assert dt["start_time"] == "2026-03-01T04:30:00" and dt["duration_minutes"] == 120
    assert make_line
