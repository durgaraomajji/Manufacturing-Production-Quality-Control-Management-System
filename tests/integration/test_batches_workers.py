from tests.helpers import (
    create_order, make_batch, make_line, make_machine, make_worker, setup_manufacturing, to_material_checked,
)


def test_batch_metrics(admin):
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids)
    batch = make_batch(admin, ids, order)
    assert batch["batch_number"] == f"{order['order_number']}-B01" and batch["status"] == "planned"
    assert batch["completion_percentage"] == 0 and batch["efficiency"] == 0

    started = admin.post(f"/production/batches/{batch['id']}/start", expect=200)
    assert started["status"] == "in_progress" and started["start_time"] and started["shift_id"]
    b = admin.post(f"/production/batches/{batch['id']}/output", {"produced": 30, "rejected": 3, "remarks": "first hour"}, expect=200)
    assert (b["produced_quantity"], b["rejected_quantity"]) == (30, 3)
    assert b["completion_percentage"] == 60.0            # 30 good of 50 planned
    assert b["rejection_percentage"] == round(3 / 33 * 100, 2)   # rejected / (good + rejected)
    assert 0 < b["efficiency"] <= 100

    b = admin.post(f"/production/batches/{batch['id']}/output", {"produced": 15, "rejected": 2}, expect=200)
    assert (b["produced_quantity"], b["rejected_quantity"]) == (45, 5) and b["completion_percentage"] == 90.0
    logs = admin.get(f"/production/batches/{batch['id']}/output-logs", order="asc")
    assert logs["total"] == 2 and [l["produced"] for l in logs["items"]] == [30, 15]

    done = admin.post(f"/production/batches/{batch['id']}/complete", expect=200)
    assert done["status"] == "completed" and done["end_time"]


def test_output_validation(admin):
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids)
    batch = make_batch(admin, ids, order, planned=20)
    admin.error("POST", f"/production/batches/{batch['id']}/output", 409, "invalid_transition", json={"produced": 1})  # not started
    admin.post(f"/production/batches/{batch['id']}/start", expect=200)
    admin.error("POST", f"/production/batches/{batch['id']}/output", 422, "validation_error", json={"produced": -1})
    admin.error("POST", f"/production/batches/{batch['id']}/output", 422, "business_rule_violation", json={"produced": 0, "rejected": 0})
    admin.error("POST", f"/production/batches/{batch['id']}/output", 422, "business_rule_violation", json={"produced": 15, "rejected": 6})
    admin.error("POST", f"/production/batches/{batch['id']}/complete", 422, "business_rule_violation")  # nothing recorded
    admin.post(f"/production/batches/{batch['id']}/output", {"produced": 20}, expect=200)
    admin.error("POST", f"/production/batches/{batch['id']}/output", 422, "business_rule_violation", json={"produced": 1})
    admin.post(f"/production/batches/{batch['id']}/complete", expect=200)
    admin.error("POST", f"/production/batches/{batch['id']}/output", 409, "invalid_transition", json={"produced": 1})
    admin.error("POST", f"/production/batches/{batch['id']}/complete", 409, "invalid_transition")


def test_batch_quantities_cannot_exceed_the_order(admin):
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids, qty=50)
    make_batch(admin, ids, order, planned=30, workers=False, machine=False)
    err = admin.error("POST", "/production/batches", 422, "business_rule_violation", json={"order_id": order["id"], "planned_quantity": 21})
    assert "remaining" in err["message"]
    second = admin.post("/production/batches", {"order_id": order["id"], "planned_quantity": 20}, expect=201)
    assert second["batch_number"].endswith("-B02")
    admin.post(f"/production/batches/{second['id']}/cancel", expect=200)  # cancelled batches free their quantity
    admin.post("/production/batches", {"order_id": order["id"], "planned_quantity": 20}, expect=201)


def test_starting_a_batch_issues_materials_exactly(admin):
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids)
    batch = make_batch(admin, ids, order, planned=20)
    admin.post(f"/production/batches/{batch['id']}/start", expect=200)
    # BOM: X x5, Y x2, Z x1 per unit  -> 100 / 40 / 20 for 20 units
    for name, left in (("X", 900), ("Y", 460), ("Z", 280)):
        assert admin.get(f"/materials/{ids['mats'][name]['id']}")["available_quantity"] == left
    assert admin.get("/inventory/transactions", batch_id=batch["id"], movement_type="consumption")["total"] == 3


def test_start_is_all_or_nothing_when_stock_runs_short(admin):
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids)
    batch = make_batch(admin, ids, order)
    # stock disappears after the availability check (Z is consumed last)
    admin.post(f"/materials/{ids['mats']['Z']['id']}/stock-out", {"quantity": 290}, expect=201)
    admin.error("POST", f"/production/batches/{batch['id']}/start", 409, "insufficient_stock")

    assert admin.get(f"/production/batches/{batch['id']}")["status"] == "planned"
    o = admin.get(f"/production/orders/{order['id']}")
    assert (o["status"], o["approval_stage"]) == ("scheduled", "material_checked")  # order start rolled back too
    for name, left in (("X", 1000), ("Y", 500), ("Z", 10)):
        assert admin.get(f"/materials/{ids['mats'][name]['id']}")["available_quantity"] == left
    assert admin.get("/inventory/transactions", movement_type="consumption")["total"] == 0


def test_worker_assignment_rules(admin):
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids)
    batch = make_batch(admin, ids, order, workers=False)
    admin.error("POST", f"/production/batches/{batch['id']}/start", 422, "business_rule_violation")  # no workers

    other_line = make_line(admin, ids["plant"]["id"], "LN-2", capacity=100)
    outsider = make_worker(admin, "EMP-9", other_line["id"])
    on_leave = make_worker(admin, "EMP-8", ids["line"]["id"], status="on_leave")
    floater = make_worker(admin, "EMP-7")  # no fixed line
    w1 = ids["workers"][0]
    admin.error("POST", f"/production/batches/{batch['id']}/workers", 422, "business_rule_violation", json={"worker_ids": [outsider["id"]]})
    admin.error("POST", f"/production/batches/{batch['id']}/workers", 422, "business_rule_violation", json={"worker_ids": [on_leave["id"]]})
    admin.error("POST", f"/production/batches/{batch['id']}/workers", 404, "not_found", json={"worker_ids": [999]})
    admin.error("POST", f"/production/batches/{batch['id']}/workers", 422, "business_rule_violation", json={"worker_ids": [w1["id"], w1["id"]]})
    admin.error("POST", f"/production/batches/{batch['id']}/workers", 422, "validation_error", json={"worker_ids": []})

    admin.post(f"/production/batches/{batch['id']}/workers", {"worker_ids": [w1["id"], floater["id"]]}, expect=201)
    admin.error("POST", f"/production/batches/{batch['id']}/workers", 409, "conflict", json={"worker_ids": [w1["id"]]})
    assert {w["employee_code"] for w in admin.get(f"/production/batches/{batch['id']}/workers")} == {"EMP-1", "EMP-7"}

    admin.delete(f"/production/batches/{batch['id']}/workers/{floater['id']}", expect=200)
    admin.error("DELETE", f"/production/batches/{batch['id']}/workers/{floater['id']}", 404, "not_found")


def test_worker_cannot_be_on_two_running_batches(admin):
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids, qty=50)
    first = make_batch(admin, ids, order, planned=20, machine=False)
    admin.post(f"/production/batches/{first['id']}/start", expect=200)
    second = admin.post("/production/batches", {"order_id": order["id"], "planned_quantity": 20}, expect=201)
    admin.error("POST", f"/production/batches/{second['id']}/workers", 409, "conflict",
                json={"worker_ids": [ids["workers"][0]["id"]]})
    # an in-progress batch must keep at least one worker
    admin.delete(f"/production/batches/{first['id']}/workers/{ids['workers'][0]['id']}", expect=200)
    admin.error("DELETE", f"/production/batches/{first['id']}/workers/{ids['workers'][1]['id']}", 422, "business_rule_violation")


def test_machine_rules_and_status_follow_the_batch(admin):
    ids = setup_manufacturing(admin)
    mid = ids["machine"]["id"]
    order = to_material_checked(admin, ids)
    other_line = make_line(admin, ids["plant"]["id"], "LN-2", capacity=100)
    foreign = make_machine(admin, other_line["id"], "MC-9")
    admin.error("POST", "/production/batches", 422, "business_rule_violation",
                json={"order_id": order["id"], "planned_quantity": 10, "machine_id": foreign["id"]})
    admin.patch(f"/machines/{mid}/status", {"status": "breakdown", "reason": "bearing"}, expect=200)
    admin.error("POST", "/production/batches", 422, "business_rule_violation",
                json={"order_id": order["id"], "planned_quantity": 10, "machine_id": mid})
    admin.patch(f"/machines/{mid}/status", {"status": "idle"}, expect=200)

    batch = make_batch(admin, ids, order)
    admin.post(f"/production/batches/{batch['id']}/start", expect=200)
    assert admin.get(f"/machines/{mid}")["status"] == "running"
    admin.error("DELETE", f"/machines/{mid}", 409, "conflict")
    admin.post(f"/production/batches/{batch['id']}/output", {"produced": 10}, expect=200)
    admin.post(f"/production/batches/{batch['id']}/complete", expect=200)
    m = admin.get(f"/machines/{mid}")
    assert m["status"] == "idle" and m["operating_hours"] >= 0


def test_my_batches_for_a_worker_account(admin, make_user):
    ids = setup_manufacturing(admin)
    worker_user = make_user("worker")
    profile = make_worker(admin, "EMP-U", ids["line"]["id"], user_id=worker_user.user["id"])
    admin.error("POST", "/production/workers", 409, "conflict",
                json={"employee_code": "EMP-X", "full_name": "Dup Link", "user_id": worker_user.user["id"]})
    order = to_material_checked(admin, ids)
    batch = admin.post("/production/batches", {"order_id": order["id"], "planned_quantity": 10}, expect=201)
    admin.post(f"/production/batches/{batch['id']}/workers", {"worker_ids": [profile["id"]]}, expect=201)
    mine = worker_user.get("/production/my-batches")
    assert mine["total"] == 1 and mine["items"][0]["id"] == batch["id"]
    assert make_user("worker").get("/production/my-batches")["total"] == 0


def test_worker_profile_management(admin):
    ids = setup_manufacturing(admin)
    w = make_worker(admin, "EMP-100", ids["line"]["id"], skill="welding", department="fabrication")
    admin.error("POST", "/production/workers", 409, "conflict", json={"employee_code": "EMP-100", "full_name": "Dup"})
    admin.error("POST", "/production/workers", 404, "not_found", json={"employee_code": "EMP-101", "full_name": "Bad Shift", "shift_id": 999})
    shift = admin.get("/production/shifts")["items"][0]
    updated = admin.patch(f"/production/workers/{w['id']}", {"shift_id": shift["id"], "status": "on_leave"}, expect=200)
    assert updated["shift_id"] == shift["id"] and updated["status"] == "on_leave"
    assert admin.get("/production/workers", skill="welding")["total"] == 1
    assert admin.get("/production/workers", department="fabrication", status="on_leave")["total"] == 1
    assert admin.get("/production/workers", search="emp-100")["total"] == 1
    assert admin.get("/production/workers", line_id=ids["line"]["id"])["total"] == 3  # 2 from setup + this one
    admin.delete(f"/production/workers/{w['id']}", expect=204)
    admin.error("GET", f"/production/workers/{w['id']}", 404)


def test_shifts_are_seeded_and_manageable(admin):
    shifts = admin.get("/production/shifts")["items"]
    assert [s["name"] for s in shifts] == ["morning", "evening", "night"]
    night = shifts[2]
    assert night["start_time"] == "22:00:00" and night["end_time"] == "06:00:00"
    admin.error("POST", "/production/shifts", 409, "conflict", json={"name": "morning", "start_time": "06:00", "end_time": "14:00"})
    assert admin.patch(f"/production/shifts/{shifts[0]['id']}", {"start_time": "07:00:00"}, expect=200)["start_time"] == "07:00:00"
    admin.error("PATCH", f"/production/shifts/{shifts[0]['id']}", 422, "business_rule_violation", json={"end_time": "07:00:00"})


def test_shift_performance(admin):
    from tests.helpers import run_full_flow
    flow = run_full_flow(admin)
    total_produced = 0
    for s in admin.get("/production/shifts")["items"]:
        perf = admin.get(f"/production/shifts/{s['id']}/performance")
        assert perf["shift_name"] == s["name"]
        total_produced += perf["produced"]
    assert total_produced == 48
    assert flow["batch"]["id"]


def test_unused(admin):
    assert create_order
