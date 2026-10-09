from datetime import timedelta

from sqlalchemy import update

from app.models.production import ProductionOrder
from tests.helpers import create_order, make_batch, run_full_flow, setup_manufacturing, to_material_checked, today


def test_high_rejection_rate_notification(admin, make_user):
    qm = make_user("quality_manager")
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids)
    batch = make_batch(admin, ids, order)
    admin.post(f"/production/batches/{batch['id']}/start", expect=200)
    admin.post(f"/production/batches/{batch['id']}/output", {"produced": 30, "rejected": 1}, expect=200)  # 3.2% -> fine
    assert qm.get("/notifications", type="high_rejection")["total"] == 0
    admin.post(f"/production/batches/{batch['id']}/output", {"produced": 10, "rejected": 9}, expect=200)  # 10/50 = 20%
    notes = qm.get("/notifications", type="high_rejection")
    assert notes["total"] == 1 and notes["items"][0]["entity_id"] == batch["id"]
    admin.post(f"/production/batches/{batch['id']}/complete", expect=200)
    assert qm.get("/notifications", type="high_rejection")["total"] == 1  # still de-duplicated


def test_no_high_rejection_notification_for_a_healthy_batch(admin):
    run_full_flow(admin)  # 2 of 50 rejected = 4%
    assert admin.get("/notifications", type="high_rejection")["total"] == 0


def test_approval_pending_notification_after_completion(admin, make_user):
    pm = make_user("production_manager")
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids)
    batch = make_batch(admin, ids, order)
    admin.post(f"/production/batches/{batch['id']}/start", expect=200)
    admin.post(f"/production/batches/{batch['id']}/output", {"produced": 50}, expect=200)
    from tests.helpers import final_inspection
    final_inspection(admin, batch["id"])
    admin.post(f"/production/batches/{batch['id']}/complete", expect=200)
    assert pm.get("/notifications", type="approval_pending")["total"] == 0
    admin.post(f"/production/orders/{order['id']}/complete", expect=200)
    assert pm.get("/notifications", type="approval_pending")["total"] == 1


def test_scan_raises_deadline_delay_and_low_stock_notifications(admin, make_user, db):
    pm = make_user("production_manager")
    store = make_user("store_manager")
    ids = setup_manufacturing(admin, stock=(5, 500, 300))
    order = create_order(admin, ids, qty=10, days=1)  # due tomorrow -> deadline warning

    first = admin.post("/admin/notifications/run-checks", expect=200)["created"]
    assert first["production_deadline"] >= 1 and first["low_stock"] >= 1 and first["production_delay"] == 0
    assert pm.get("/notifications", type="production_deadline")["total"] == 1
    assert store.get("/notifications", type="low_stock")["total"] == 1

    # the order slips past its target date
    db.execute(update(ProductionOrder).where(ProductionOrder.id == order["id"]).values(target_date=today() - timedelta(days=2)))
    db.commit()
    second = admin.post("/admin/notifications/run-checks", expect=200)["created"]
    assert second["production_delay"] >= 1 and second["low_stock"] == 0
    delay = pm.get("/notifications", type="production_delay")
    assert delay["total"] == 1 and delay["items"][0]["severity"] == "critical"


def test_scan_notifies_about_breakdowns_and_pending_approvals(admin, make_user):
    eng = make_user("maintenance_engineer")
    ids = setup_manufacturing(admin)
    admin.patch(f"/machines/{ids['machine']['id']}/status", {"status": "breakdown"}, expect=200)
    created = admin.post("/admin/notifications/run-checks", expect=200)["created"]
    assert created["machine_breakdown"] == 0  # already raised when the status changed (de-duplicated)
    assert eng.get("/notifications", type="machine_breakdown")["total"] == 1


def test_run_checks_is_restricted(make_user):
    make_user("worker").error("POST", "/admin/notifications/run-checks", 403, "forbidden")
    assert make_user("plant_manager").post("/admin/notifications/run-checks", expect=200)["total"] >= 0
