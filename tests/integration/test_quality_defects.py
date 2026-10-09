from tests.helpers import final_inspection, make_batch, make_material, setup_manufacturing, to_material_checked


def started_batch(admin, produced=20, planned=50):
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids, qty=planned)
    batch = make_batch(admin, ids, order, planned=planned)
    admin.post(f"/production/batches/{batch['id']}/start", expect=200)
    if produced:
        admin.post(f"/production/batches/{batch['id']}/output", {"produced": produced}, expect=200)
    return ids, order, batch


def test_inspection_pass_and_fail_derivation(admin):
    _, _, batch = started_batch(admin)
    body = {"batch_id": batch["id"], "inspection_type": "in_process", "remarks": "hourly check", "parameters": [
        {"name": "Diameter", "expected_value": "25.0", "actual_value": "25.2", "tolerance": 0.5},
        {"name": "Colour", "expected_value": "Grey", "actual_value": "grey"},
        {"name": "Weight", "expected_value": "100", "actual_value": "100"}]}
    insp = admin.post("/inspections", body, expect=201)
    assert insp["result"] == "pass" and all(p["passed"] for p in insp["parameters"])
    assert insp["inspector_id"] and insp["inspection_type"] == "in_process" and insp["inspection_date"]

    body["parameters"][0]["actual_value"] = "26.0"  # outside tolerance
    failed = admin.post("/inspections", body, expect=201)
    assert failed["result"] == "fail"
    assert [p["name"] for p in failed["parameters"] if not p["passed"]] == ["Diameter"]

    body["parameters"][0]["passed"] = True  # explicit verdict by the inspector wins
    assert admin.post("/inspections", body, expect=201)["result"] == "pass"


def test_inspection_validation(admin):
    ids, order, batch = started_batch(admin, produced=0)
    p = [{"name": "x", "expected_value": "1", "actual_value": "1"}]
    admin.error("POST", "/inspections", 422, "validation_error", json={"batch_id": batch["id"], "inspection_type": "in_process", "parameters": []})
    admin.error("POST", "/inspections", 422, "validation_error", json={"batch_id": batch["id"], "inspection_type": "bogus", "parameters": p})
    admin.error("POST", "/inspections", 404, "not_found", json={"batch_id": 999, "inspection_type": "in_process", "parameters": p})
    # final inspection needs output; incoming material inspection needs a material
    admin.error("POST", "/inspections", 422, "business_rule_violation", json={"batch_id": batch["id"], "inspection_type": "final_product", "parameters": p})
    admin.error("POST", "/inspections", 422, "business_rule_violation", json={"batch_id": batch["id"], "inspection_type": "incoming_material", "parameters": p})
    ok = admin.post("/inspections", {"batch_id": batch["id"], "inspection_type": "incoming_material",
                                     "material_id": ids["mats"]["X"]["id"], "parameters": p}, expect=201)
    assert ok["material_id"] == ids["mats"]["X"]["id"]
    admin.error("POST", "/inspections", 404, "not_found",
                json={"batch_id": batch["id"], "inspection_type": "incoming_material", "material_id": 999, "parameters": p})


def test_in_process_inspection_needs_a_started_batch(admin):
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids)
    batch = make_batch(admin, ids, order)
    admin.error("POST", "/inspections", 422, "business_rule_violation", json={
        "batch_id": batch["id"], "inspection_type": "in_process", "parameters": [{"name": "x", "expected_value": "1", "actual_value": "1"}]})


def test_inspection_listing_filters(admin):
    _, _, batch = started_batch(admin)
    final_inspection(admin, batch["id"])
    final_inspection(admin, batch["id"], actual="99")
    admin.post("/inspections", {"batch_id": batch["id"], "inspection_type": "in_process",
                                "parameters": [{"name": "x", "expected_value": "1", "actual_value": "1"}]}, expect=201)
    assert admin.get("/inspections")["total"] == 3
    assert admin.get("/inspections", result="fail")["total"] == 1
    assert admin.get("/inspections", inspection_type="final_product")["total"] == 2
    assert admin.get("/inspections", batch_id=batch["id"], inspection_type="in_process")["total"] == 1
    assert admin.get("/inspections", date_from="2000-01-01", date_to="2000-01-31")["total"] == 0
    one = admin.get("/inspections")["items"][0]
    assert admin.get(f"/inspections/{one['id']}")["id"] == one["id"]


def test_only_quality_manager_inspects(admin, make_user):
    _, _, batch = started_batch(admin)
    qm = make_user("quality_manager")
    insp = final_inspection(qm, batch["id"])
    assert insp["inspector_id"] == qm.user["id"]
    make_user("production_manager").error("POST", "/inspections", 403, "forbidden", json={
        "batch_id": batch["id"], "inspection_type": "in_process", "parameters": [{"name": "x", "expected_value": "1", "actual_value": "1"}]})


def test_defect_creation_and_validation(admin):
    ids, _, batch = started_batch(admin)
    d = admin.post("/defects", {"batch_id": batch["id"], "defect_type": "Crack", "severity": "major", "quantity_affected": 5,
                                "root_cause": "Overheating", "corrective_action": "Lower temperature"}, expect=201)
    assert d["product_id"] == ids["product"]["id"] and d["resolution_status"] == "open" and d["reported_by_id"]
    admin.error("POST", "/defects", 422, "business_rule_violation", json={"batch_id": batch["id"], "defect_type": "Crack", "severity": "minor", "quantity_affected": 51})
    admin.error("POST", "/defects", 422, "validation_error", json={"batch_id": batch["id"], "defect_type": "Crack", "severity": "minor", "quantity_affected": 0})
    admin.error("POST", "/defects", 422, "validation_error", json={"batch_id": batch["id"], "defect_type": "Crack", "severity": "catastrophic", "quantity_affected": 1})
    other_product = admin.post("/products", {"sku": "OTHER", "name": "Other"}, expect=201)
    admin.error("POST", "/defects", 422, "business_rule_violation",
                json={"batch_id": batch["id"], "product_id": other_product["id"], "defect_type": "Crack", "severity": "minor", "quantity_affected": 1})
    admin.error("POST", "/defects", 404, "not_found", json={"batch_id": 999, "defect_type": "Crack", "severity": "minor", "quantity_affected": 1})


def test_defect_can_be_linked_to_an_inspection(admin):
    from tests.helpers import make_worker
    ids = setup_manufacturing(admin)
    order = to_material_checked(admin, ids, qty=50)
    a = make_batch(admin, ids, order, planned=25)
    admin.post(f"/production/batches/{a['id']}/start", expect=200)
    admin.post(f"/production/batches/{a['id']}/output", {"produced": 10}, expect=200)
    insp = final_inspection(admin, a["id"], actual="50")
    d = admin.post("/defects", {"batch_id": a["id"], "inspection_id": insp["id"], "defect_type": "Oversize",
                                "severity": "minor", "quantity_affected": 2}, expect=201)
    assert d["inspection_id"] == insp["id"]

    # an inspection of another batch cannot be attached
    w3 = make_worker(admin, "EMP-3", ids["line"]["id"])
    b = admin.post("/production/batches", {"order_id": order["id"], "planned_quantity": 25}, expect=201)
    admin.post(f"/production/batches/{b['id']}/workers", {"worker_ids": [w3["id"]]}, expect=201)
    admin.post(f"/production/batches/{b['id']}/start", expect=200)
    admin.error("POST", "/defects", 422, "business_rule_violation", json={
        "batch_id": b["id"], "inspection_id": insp["id"], "defect_type": "Oversize", "severity": "minor", "quantity_affected": 1})


def test_critical_defect_notifies_the_quality_team(admin, make_user):
    qm = make_user("quality_manager")
    worker = make_user("worker")
    _, _, batch = started_batch(admin)
    d = admin.post("/defects", {"batch_id": batch["id"], "defect_type": "Weld failure", "severity": "critical", "quantity_affected": 4}, expect=201)
    notes = qm.get("/notifications", type="critical_defect")
    assert notes["total"] == 1 and notes["items"][0]["severity"] == "critical" and notes["items"][0]["entity_id"] == d["id"]
    assert admin.get("/notifications", type="critical_defect")["total"] == 1  # super admin is always informed
    assert worker.get("/notifications")["total"] == 0
    # minor defects do not notify
    admin.post("/defects", {"batch_id": batch["id"], "defect_type": "Scuff", "severity": "minor", "quantity_affected": 1}, expect=201)
    assert qm.get("/notifications", type="critical_defect")["total"] == 1

    assert qm.get("/notifications/unread-count")["unread"] >= 1
    qm.post(f"/notifications/{notes['items'][0]['id']}/read", expect=200)
    qm.post("/notifications/read-all", expect=200)
    assert qm.get("/notifications/unread-count")["unread"] == 0
    assert qm.get("/notifications", is_read=True)["total"] >= 1


def test_defect_resolution_workflow(admin):
    _, _, batch = started_batch(admin)
    d = admin.post("/defects", {"batch_id": batch["id"], "defect_type": "Burr", "severity": "minor", "quantity_affected": 3}, expect=201)
    did = d["id"]
    admin.error("PATCH", f"/defects/{did}", 409, "invalid_transition", json={"resolution_status": "closed"})  # cannot skip ahead
    err = admin.error("PATCH", f"/defects/{did}", 422, "business_rule_violation", json={"resolution_status": "resolved"})
    assert "corrective" in err["message"]

    assert admin.patch(f"/defects/{did}", {"resolution_status": "in_progress", "root_cause": "Dull blade"}, expect=200)["resolution_status"] == "in_progress"
    resolved = admin.patch(f"/defects/{did}", {"resolution_status": "resolved", "corrective_action": "Replaced blade"}, expect=200)
    assert resolved["resolution_status"] == "resolved" and resolved["resolved_at"] and resolved["corrective_action"] == "Replaced blade"
    reopened = admin.patch(f"/defects/{did}", {"resolution_status": "in_progress"}, expect=200)
    assert reopened["resolved_at"] is None
    admin.patch(f"/defects/{did}", {"resolution_status": "resolved"}, expect=200)
    assert admin.patch(f"/defects/{did}", {"resolution_status": "closed"}, expect=200)["resolution_status"] == "closed"
    admin.error("PATCH", f"/defects/{did}", 409, "invalid_transition", json={"resolution_status": "open"})
    admin.error("PATCH", f"/defects/{did}", 422, "business_rule_violation", json={"quantity_affected": 999})


def test_defect_filters(admin):
    ids, _, batch = started_batch(admin)
    for sev, n in (("minor", 1), ("major", 2), ("critical", 3)):
        admin.post("/defects", {"batch_id": batch["id"], "defect_type": f"{sev} issue", "severity": sev, "quantity_affected": n}, expect=201)
    assert admin.get("/defects")["total"] == 3
    assert admin.get("/defects", severity="critical")["items"][0]["quantity_affected"] == 3
    assert admin.get("/defects", batch_id=batch["id"], product_id=ids["product"]["id"])["total"] == 3
    assert admin.get("/defects", resolution_status="resolved")["total"] == 0
    assert admin.get("/defects", search="major")["total"] == 1
    assert admin.get("/defects", size=2)["pages"] == 2


def test_quality_and_defect_records_are_audited(admin):
    _, _, batch = started_batch(admin)
    final_inspection(admin, batch["id"])
    admin.post("/defects", {"batch_id": batch["id"], "defect_type": "Dent", "severity": "minor", "quantity_affected": 1}, expect=201)
    assert admin.get("/admin/audit-logs", action="quality.inspection")["total"] == 1
    assert admin.get("/admin/audit-logs", action="defect.create")["total"] == 1
    assert make_material
