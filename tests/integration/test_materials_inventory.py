from tests.helpers import make_material, run_full_flow, setup_manufacturing


def test_material_lifecycle_and_stock_rules(admin):
    m = make_material(admin, "STL-1", 100, minimum=20, reorder=30, supplier_reference="ACME")
    assert m["available_quantity"] == 100 and m["is_low_stock"] is False
    admin.error("POST", "/materials", 409, "conflict", json={"code": "STL-1", "name": "dup"})

    txn = admin.post(f"/materials/{m['id']}/stock-in", {"quantity": 50, "reference": "PO-77"}, expect=201)
    assert (txn["balance_before"], txn["balance_after"], txn["movement_type"]) == (100, 150, "receipt")
    txn = admin.post(f"/materials/{m['id']}/stock-out", {"quantity": 120}, expect=201)
    assert txn["balance_after"] == 30 and admin.get(f"/materials/{m['id']}")["is_low_stock"] is True

    err = admin.error("POST", f"/materials/{m['id']}/stock-out", 409, "insufficient_stock", json={"quantity": 31})
    assert err["details"]["available"] == 30
    assert admin.get(f"/materials/{m['id']}")["available_quantity"] == 30  # untouched

    admin.error("POST", f"/materials/{m['id']}/stock-in", 422, "validation_error", json={"quantity": 0})
    admin.error("POST", f"/materials/{m['id']}/stock-out", 422, "validation_error", json={"quantity": -5})

    adj = admin.post(f"/materials/{m['id']}/adjust", {"new_quantity": 28, "reason": "cycle count"}, expect=201)
    assert adj["delta"] == -2 and adj["movement_type"] == "adjustment"
    admin.error("POST", f"/materials/{m['id']}/adjust", 422, "business_rule_violation", json={"new_quantity": 28, "reason": "same"})


def test_quantity_cannot_be_edited_directly(admin):
    m = make_material(admin, "STL-2", 10)
    updated = admin.patch(f"/materials/{m['id']}", {"available_quantity": 9999, "name": "Steel"}, expect=200)
    assert updated["available_quantity"] == 10 and updated["name"] == "Steel"


def test_inactive_material_cannot_move(admin):
    m = make_material(admin, "STL-3", 10)
    admin.patch(f"/materials/{m['id']}", {"status": "inactive"}, expect=200)
    admin.error("POST", f"/materials/{m['id']}/stock-in", 422, "business_rule_violation", json={"quantity": 1})


def test_material_search_filters_and_low_stock_list(admin):
    cat = admin.post("/material-categories", {"name": "Metals"}, expect=201)
    make_material(admin, "AL-1", 5, minimum=10, category_id=cat["id"])
    make_material(admin, "CU-1", 500, minimum=10, category_id=cat["id"], supplier_reference="Globex")
    make_material(admin, "PL-1", 50)
    assert admin.get("/materials", search="al-")["total"] == 1
    assert admin.get("/materials", category_id=cat["id"])["total"] == 2
    assert admin.get("/materials", supplier_reference="Globex")["items"][0]["code"] == "CU-1"
    assert [m["code"] for m in admin.get("/materials/low-stock")] == ["AL-1"]


def test_delete_material_rules(admin):
    ids = setup_manufacturing(admin)
    x = ids["mats"]["X"]
    admin.error("DELETE", f"/materials/{x['id']}", 409, "conflict")  # used by the active BOM
    spare = make_material(admin, "SPARE", 0)
    admin.delete(f"/materials/{spare['id']}", expect=204)
    admin.error("GET", f"/materials/{spare['id']}", 404)
    stocked = make_material(admin, "STOCKED", 5)
    admin.error("DELETE", f"/materials/{stocked['id']}", 422, "business_rule_violation")


def test_transaction_history_and_usage_history(admin):
    flow = run_full_flow(admin)
    x = flow["mats"]["X"]
    usage = admin.get(f"/materials/{x['id']}/usage-history")
    assert usage["total"] == 1 and usage["items"][0]["movement_type"] == "consumption" and usage["items"][0]["quantity"] == 250
    assert usage["items"][0]["batch_id"] == flow["batch"]["id"]

    ledger = admin.get("/inventory/transactions", material_id=x["id"], sort_by="id", order="asc")
    assert [t["movement_type"] for t in ledger["items"]] == ["receipt", "consumption"]
    assert ledger["items"][-1]["balance_after"] == 750

    finished = admin.get("/inventory/transactions", product_id=flow["product"]["id"], sort_by="id", order="asc")
    assert [(t["movement_type"], t["delta"]) for t in finished["items"]] == [("finished_goods", 48), ("rejected_goods", 0)]
    assert finished["items"][1]["quantity"] == 2
    assert admin.get("/inventory/transactions", movement_type="consumption")["total"] == 3
    assert admin.get("/inventory/transactions", batch_id=flow["batch"]["id"])["total"] == 3
    assert admin.get("/inventory/transactions", date_from="2000-01-01", date_to="2000-01-02")["total"] == 0


def test_inventory_summary_and_finished_goods(admin):
    flow = run_full_flow(admin)
    s = admin.get("/inventory/summary")
    assert s["total_materials"] == 3 and s["total_finished_goods_units"] == 48 and s["transactions_today"] >= 5
    fg = admin.get("/inventory/finished-goods")
    assert fg["items"][0]["stock_quantity"] == 48
    adj = admin.post(f"/inventory/finished-goods/{flow['product']['id']}/adjust", {"new_quantity": 45, "reason": "damaged in storage"}, expect=201)
    assert adj["delta"] == -3 and adj["balance_after"] == 45


def test_stock_movements_are_audited(admin):
    m = make_material(admin, "AUD-1", 10)
    admin.post(f"/materials/{m['id']}/stock-out", {"quantity": 4}, expect=200 if False else 201)
    admin.post(f"/materials/{m['id']}/adjust", {"new_quantity": 1, "reason": "count"}, expect=201)
    actions = [l["action"] for l in admin.get("/admin/audit-logs", entity="material", entity_id=m["id"], sort_by="id", order="asc")["items"]]
    assert actions == ["material.create", "material.movement", "material.movement", "inventory.adjustment"]
