from datetime import timedelta

from tests.helpers import (
    create_order, final_inspection, make_batch, make_material, make_product, run_full_flow, setup_manufacturing, to_material_checked,
    today,
)


def stage(api, order_id):
    o = api.get(f"/production/orders/{order_id}")
    return o["status"], o["approval_stage"]


# ---------------------------------------------------------------- order creation rules
def test_create_order_defaults(admin):
    ids = setup_manufacturing(admin)
    order = create_order(admin, ids, qty=50)
    assert order["order_number"].startswith("PO-") and order["status"] == "draft" and order["approval_stage"] == "created"
    assert order["bom_id"] == ids["bom"]["id"] and order["produced_quantity"] == 0 and order["completion_percentage"] == 0
    assert create_order(admin, ids)["order_number"] != order["order_number"]


def test_create_order_validation(admin):
    ids = setup_manufacturing(admin)
    base = {"product_id": ids["product"]["id"], "quantity": 10, "target_date": str(today() + timedelta(days=3)), "line_id": ids["line"]["id"]}
    admin.error("POST", "/production/orders", 422, "validation_error", json={**base, "quantity": 0})
    admin.error("POST", "/production/orders", 422, "business_rule_violation", json={**base, "target_date": str(today() - timedelta(days=1))})
    admin.error("POST", "/production/orders", 404, "not_found", json={**base, "product_id": 999})
    admin.error("POST", "/production/orders", 404, "not_found", json={**base, "line_id": 999})
    # capacity: line makes 500/day; 5 days from now => at most 3000 units
    err = admin.error("POST", "/production/orders", 422, "business_rule_violation", json={**base, "quantity": 5000})
    assert "capacity" in err["message"]
    inactive = make_product(admin, "OLD-1", status="inactive")
    admin.error("POST", "/production/orders", 422, "business_rule_violation", json={**base, "product_id": inactive["id"]})


def test_cannot_produce_on_inactive_line_or_closed_plant(admin):
    ids = setup_manufacturing(admin)
    admin.patch(f"/production-lines/{ids['line']['id']}", {"status": "maintenance"}, expect=200)
    body = {"product_id": ids["product"]["id"], "quantity": 10, "target_date": str(today()), "line_id": ids["line"]["id"]}
    admin.error("POST", "/production/orders", 422, "business_rule_violation", json=body)
    admin.patch(f"/production-lines/{ids['line']['id']}", {"status": "active"}, expect=200)
    admin.patch(f"/plants/{ids['plant']['id']}/status", {"status": "temporarily_closed"}, expect=200)
    admin.error("POST", "/production/orders", 422, "business_rule_violation", json=body)


def test_only_drafts_can_be_edited_or_deleted(admin):
    ids = setup_manufacturing(admin)
    order = create_order(admin, ids)
    assert admin.patch(f"/production/orders/{order['id']}", {"quantity": 20, "priority": "urgent"}, expect=200)["quantity"] == 20
    admin.post(f"/production/orders/{order['id']}/review", expect=200)
    admin.error("PATCH", f"/production/orders/{order['id']}", 409, "invalid_transition", json={"quantity": 30})
    admin.error("DELETE", f"/production/orders/{order['id']}", 409, "invalid_transition")
    draft = create_order(admin, ids)
    admin.delete(f"/production/orders/{draft['id']}", expect=204)
    admin.error("GET", f"/production/orders/{draft['id']}", 404)


# ---------------------------------------------------------------- approval workflow
def test_workflow_cannot_be_skipped_or_repeated(admin):
    ids = setup_manufacturing(admin)
    o = create_order(admin, ids)
    oid = o["id"]
    for action in ("check-materials", "start", "complete", "approve"):
        admin.error("POST", f"/production/orders/{oid}/{action}", 409, "invalid_transition")
    admin.error("POST", f"/production/batches", 409, "invalid_transition", json={"order_id": oid, "planned_quantity": 10})

    reviewed = admin.post(f"/production/orders/{oid}/review", {"comments": "looks fine"}, expect=200)
    assert (reviewed["status"], reviewed["approval_stage"]) == ("scheduled", "supervisor_reviewed")
    admin.error("POST", f"/production/orders/{oid}/review", 409, "invalid_transition")  # no repeats
    admin.error("POST", f"/production/orders/{oid}/start", 409, "invalid_transition")  # materials not checked yet
    assert admin.post(f"/production/orders/{oid}/check-materials", expect=200)["approval_stage"] == "material_checked"

    started = admin.post(f"/production/orders/{oid}/start", expect=200)
    assert (started["status"], started["approval_stage"]) == ("in_progress", "production_started")
    assert started["started_at"] is not None
    admin.error("POST", f"/production/orders/{oid}/start", 409, "invalid_transition")
    admin.error("POST", f"/production/orders/{oid}/complete", 409, "invalid_transition")  # no inspection yet
    admin.error("POST", f"/production/orders/{oid}/approve", 409, "invalid_transition")


def test_supervisor_review_is_limited_to_the_assigned_supervisor(admin, make_user):
    ids = setup_manufacturing(admin)
    sup1, sup2 = make_user("production_supervisor"), make_user("production_supervisor")
    order = create_order(admin, ids, supervisor_id=sup1.user["id"])
    sup2.error("POST", f"/production/orders/{order['id']}/review", 403, "forbidden")
    assert sup1.post(f"/production/orders/{order['id']}/review", expect=200)["reviewed_by_id"] == sup1.user["id"]
    admin.error("POST", "/production/orders", 422, "business_rule_violation", json={
        "product_id": ids["product"]["id"], "quantity": 5, "target_date": str(today()), "line_id": ids["line"]["id"],
        "supervisor_id": make_user("worker").user["id"]})


def test_material_shortage_blocks_the_workflow_until_fixed(admin):
    ids = setup_manufacturing(admin, stock=(100, 500, 300))  # X needs 250 for 50 units
    order = create_order(admin, ids, qty=50)
    admin.post(f"/production/orders/{order['id']}/review", expect=200)

    avail = admin.get(f"/production/orders/{order['id']}/material-availability")
    by_code = {i["material_code"]: i for i in avail["items"]}
    assert avail["sufficient"] is False
    assert (by_code["MAT-X"]["required_quantity"], by_code["MAT-X"]["shortage"]) == (250, 150)
    assert by_code["MAT-Y"]["required_quantity"] == 100 and by_code["MAT-Y"]["sufficient"] is True

    result = admin.post(f"/production/orders/{order['id']}/check-materials", expect=200)
    assert result["sufficient"] is False and result["approval_stage"] == "supervisor_reviewed" and "MAT-X" in result["message"]
    admin.error("POST", f"/production/orders/{order['id']}/start", 409, "invalid_transition")

    admin.post(f"/materials/{ids['mats']['X']['id']}/stock-in", {"quantity": 150}, expect=201)
    ok = admin.post(f"/production/orders/{order['id']}/check-materials", expect=200)
    assert ok["sufficient"] is True and ok["approval_stage"] == "material_checked"


def test_approval_history_records_each_step(admin):
    flow = run_full_flow(admin)
    history = admin.get(f"/production/orders/{flow['order']['id']}/approval-history")
    assert [h["to_stage"] for h in history] == [
        "created", "supervisor_reviewed", "material_checked", "production_started",
        "quality_inspected", "production_completed", "manager_approved"]
    assert history[0]["from_stage"] is None and history[1]["from_stage"] == "created"
    assert all(h["user_id"] for h in history)
    final = admin.get(f"/production/orders/{flow['order']['id']}")
    assert final["status"] == "completed" and final["approval_stage"] == "manager_approved"
    assert final["approved_by_id"] and final["completed_at"] and final["produced_quantity"] == 48 and final["rejected_quantity"] == 2
    assert final["completion_percentage"] == 96.0


def test_final_inspection_failure_does_not_advance_the_stage(admin):
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids)
    batch = make_batch(admin, ids, order)
    admin.post(f"/production/batches/{batch['id']}/start", expect=200)
    admin.post(f"/production/batches/{batch['id']}/output", {"produced": 50}, expect=200)
    failed = final_inspection(admin, batch["id"], expected="10", actual="12")
    assert failed["result"] == "fail"
    assert stage(admin, order["id"]) == ("in_progress", "production_started")
    admin.post(f"/production/batches/{batch['id']}/complete", expect=200)
    admin.error("POST", f"/production/orders/{order['id']}/complete", 409, "invalid_transition")
    assert final_inspection(admin, batch["id"])["result"] == "pass"
    assert stage(admin, order["id"]) == ("in_progress", "quality_inspected")
    admin.post(f"/production/orders/{order['id']}/complete", expect=200)


# ---------------------------------------------------------------- pause / resume / cancel
def test_pause_resume_and_cancel(admin):
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids)
    oid = order["id"]
    admin.error("POST", f"/production/orders/{oid}/status", 409, "invalid_transition", json={"status": "paused"})  # not started
    batch = make_batch(admin, ids, order)
    admin.post(f"/production/batches/{batch['id']}/start", expect=200)

    assert admin.post(f"/production/orders/{oid}/status", {"status": "paused", "reason": "power cut"}, expect=200)["status"] == "paused"
    admin.error("POST", f"/production/batches/{batch['id']}/output", 422, "business_rule_violation", json={"produced": 1})
    admin.error("POST", f"/production/orders/{oid}/status", 409, "invalid_transition", json={"status": "paused"})
    assert admin.post(f"/production/orders/{oid}/status", {"status": "in_progress"}, expect=200)["status"] == "in_progress"
    admin.post(f"/production/batches/{batch['id']}/output", {"produced": 1}, expect=200)

    admin.error("POST", f"/production/orders/{oid}/status", 422, "business_rule_violation", json={"status": "cancelled"})  # batch running
    admin.error("POST", f"/production/orders/{oid}/status", 422, "business_rule_violation", json={"status": "completed"})
    admin.error("POST", f"/production/orders/{oid}/status", 422, "validation_error", json={"status": "nonsense"})


def test_cancel_draft_and_terminal_states(admin):
    ids = setup_manufacturing(admin)
    order = create_order(admin, ids)
    cancelled = admin.post(f"/production/orders/{order['id']}/status", {"status": "cancelled", "reason": "customer request"}, expect=200)
    assert cancelled["status"] == "cancelled" and "customer request" in cancelled["remarks"]
    for action in ("review", "check-materials", "start", "complete"):
        admin.error("POST", f"/production/orders/{order['id']}/{action}", 409, "invalid_transition")
    admin.error("POST", f"/production/orders/{order['id']}/status", 409, "invalid_transition", json={"status": "cancelled"})
    admin.delete(f"/production/orders/{order['id']}", expect=204)  # cancelled orders may be removed


def test_supervisor_can_pause_but_not_cancel(admin, make_user):
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids)
    batch = make_batch(admin, ids, order)
    admin.post(f"/production/batches/{batch['id']}/start", expect=200)
    sup = make_user("production_supervisor")
    assert sup.post(f"/production/orders/{order['id']}/status", {"status": "paused"}, expect=200)["status"] == "paused"
    sup.error("POST", f"/production/orders/{order['id']}/status", 403, "forbidden", json={"status": "cancelled"})


# ---------------------------------------------------------------- completion & inventory
def test_completing_an_order_books_finished_goods(admin):
    flow = run_full_flow(admin)
    assert admin.get(f"/products/{flow['product']['id']}")["stock_quantity"] == 48
    for name, left in (("X", 750), ("Y", 400), ("Z", 250)):
        assert admin.get(f"/materials/{flow['mats'][name]['id']}")["available_quantity"] == left


def test_order_completion_requires_finished_batches(admin):
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids)
    batch = make_batch(admin, ids, order)
    admin.post(f"/production/batches/{batch['id']}/start", expect=200)
    admin.post(f"/production/batches/{batch['id']}/output", {"produced": 50}, expect=200)
    final_inspection(admin, batch["id"])
    err = admin.error("POST", f"/production/orders/{order['id']}/complete", 422, "business_rule_violation")
    assert "batch" in err["message"].lower()


def test_order_listing_filters(admin):
    ids = setup_manufacturing(admin)
    o1 = create_order(admin, ids, qty=10, priority="low")
    o2 = create_order(admin, ids, qty=20, priority="urgent", days=10)
    admin.post(f"/production/orders/{o2['id']}/review", expect=200)
    assert admin.get("/production/orders")["total"] == 2
    assert admin.get("/production/orders", status="scheduled")["items"][0]["id"] == o2["id"]
    assert admin.get("/production/orders", priority="low")["items"][0]["id"] == o1["id"]
    assert admin.get("/production/orders", approval_stage="supervisor_reviewed")["total"] == 1
    assert admin.get("/production/orders", plant_id=ids["plant"]["id"])["total"] == 2
    assert admin.get("/production/orders", plant_id=999)["total"] == 0
    assert admin.get("/production/orders", target_from=str(today() + timedelta(days=8)))["total"] == 1
    assert admin.get("/production/orders", search="PO-")["total"] == 2
    assert [o["quantity"] for o in admin.get("/production/orders", sort_by="quantity", order="asc")["items"]] == [10, 20]


def test_plant_cannot_be_closed_while_orders_are_in_production(admin):
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids)
    batch = make_batch(admin, ids, order)
    admin.post(f"/production/batches/{batch['id']}/start", expect=200)
    admin.error("PATCH", f"/plants/{ids['plant']['id']}/status", 422, "business_rule_violation", json={"status": "inactive"})
    admin.error("PATCH", f"/production-lines/{ids['line']['id']}", 422, "business_rule_violation", json={"status": "inactive"})


def test_order_workflow_is_audited(admin):
    flow = run_full_flow(admin)
    logs = admin.get("/admin/audit-logs", entity="production_order", entity_id=flow["order"]["id"], sort_by="id", order="asc", size=50)
    assert [l["action"] for l in logs["items"]] == [
        "production_order.create", "production_order.review", "production_order.material_check", "production_order.start",
        "production_order.complete", "production_order.approve"]
    approve = logs["items"][-1]
    assert approve["previous_value"]["approval_stage"] == "production_completed" and approve["new_value"]["approval_stage"] == "manager_approved"
    assert approve["user_id"] and approve["timestamp"]


def test_unused_helpers_stay_importable():
    assert callable(make_material)
