"""The mandatory end-to-end scenario from the brief:

Admin Login -> Create Plant -> Create Production Line -> Create Product -> Create BOM -> Add Raw Materials ->
Register Machine -> Create Production Order -> Check Material Availability -> Assign Workers -> Start Production
Batch -> Record Production Output -> Perform Quality Inspection -> Record Defects -> Complete Production ->
Update Inventory -> Schedule Machine Maintenance -> Generate Dashboard -> Generate Reports -> Verify Audit Logs
"""
from datetime import timedelta

from tests.helpers import Api, today


def test_mandatory_end_to_end_flow(client):
    # 1. Admin login
    r = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "Admin@12345"})
    assert r.status_code == 200
    api = Api(client, {"Authorization": f"Bearer {r.json()['access_token']}"})
    assert api.get("/auth/me")["role"] == "super_admin"

    # 2-3. Plant and production line
    plant = api.post("/plants", {"code": "PLT-E2E", "name": "E2E Plant", "production_capacity": 2000, "city": "Pune",
                                 "address_line": "Gate 1", "country": "IN"}, expect=201)
    line = api.post("/production-lines", {"line_code": "L-ASM-1", "name": "Assembly 1", "plant_id": plant["id"],
                                          "production_capacity": 1000}, expect=201)

    # 4. Product (+ category)
    category = api.post("/product-categories", {"name": "Assemblies"}, expect=201)
    product = api.post("/products", {"sku": "ASM-A", "name": "Assembly A", "category_id": category["id"],
                                     "unit_of_measure": "pcs", "standard_production_time": 3.0}, expect=201)

    # 5-6. Raw materials (empty stock first), BOM: X x5, Y x2, Z x1, then receive the stock
    mats = {}
    for code, unit in (("RM-X", "kg"), ("RM-Y", "m"), ("RM-Z", "pcs")):
        mats[code] = api.post("/materials", {"code": code, "name": f"Raw {code}", "unit": unit, "minimum_stock_level": 20,
                                             "reorder_level": 50, "supplier_reference": "SUP-1"}, expect=201)
    bom = api.post("/boms", {"product_id": product["id"], "name": "Assembly A v1", "activate": True, "items": [
        {"material_id": mats["RM-X"]["id"], "quantity_per_unit": 5},
        {"material_id": mats["RM-Y"]["id"], "quantity_per_unit": 2},
        {"material_id": mats["RM-Z"]["id"], "quantity_per_unit": 1}]}, expect=201)
    assert bom["version"] == 1 and bom["is_active"]
    for code, qty in (("RM-X", 600), ("RM-Y", 300), ("RM-Z", 150)):
        api.post(f"/materials/{mats[code]['id']}/stock-in", {"quantity": qty, "reference": "PO-1"}, expect=201)

    # 7. Machine
    machine = api.post("/machines", {"machine_code": "ASM-M1", "name": "Press 1", "machine_type": "Press", "line_id": line["id"],
                                     "installation_date": "2024-05-01", "maintenance_interval_days": 90}, expect=201)

    # 8. Production order
    order = api.post("/production/orders", {"product_id": product["id"], "quantity": 100,
                                            "target_date": str(today() + timedelta(days=7)), "line_id": line["id"],
                                            "priority": "high"}, expect=201)
    assert order["status"] == "draft"

    # 9. Material availability: 100 units need X 500, Y 200, Z 100
    availability = api.get(f"/production/orders/{order['id']}/material-availability")
    assert availability["sufficient"] is True
    assert {i["material_code"]: i["required_quantity"] for i in availability["items"]} == {"RM-X": 500, "RM-Y": 200, "RM-Z": 100}
    api.post(f"/production/orders/{order['id']}/review", {"comments": "approved by supervisor"}, expect=200)
    checked = api.post(f"/production/orders/{order['id']}/check-materials", expect=200)
    assert checked["sufficient"] and checked["approval_stage"] == "material_checked"

    # 10. Workers
    workers = [api.post("/production/workers", {"employee_code": f"W-{i}", "full_name": f"Operator {i}", "skill": "pressing",
                                                "department": "assembly", "line_id": line["id"]}, expect=201) for i in (1, 2, 3)]
    batch = api.post("/production/batches", {"order_id": order["id"], "planned_quantity": 100, "machine_id": machine["id"]}, expect=201)
    api.post(f"/production/batches/{batch['id']}/workers", {"worker_ids": [w["id"] for w in workers]}, expect=201)

    # 11. Start batch (issues materials and starts the order + machine)
    started = api.post(f"/production/batches/{batch['id']}/start", expect=200)
    assert started["status"] == "in_progress"
    assert api.get(f"/production/orders/{order['id']}")["status"] == "in_progress"
    assert api.get(f"/machines/{machine['id']}")["status"] == "running"
    assert api.get(f"/materials/{mats['RM-X']['id']}")["available_quantity"] == 100  # 600 - 500

    # 12. Production output in two shifts of work
    api.post(f"/production/batches/{batch['id']}/output", {"produced": 55, "rejected": 3}, expect=200)
    b = api.post(f"/production/batches/{batch['id']}/output", {"produced": 38, "rejected": 4}, expect=200)
    assert (b["produced_quantity"], b["rejected_quantity"]) == (93, 7)
    assert b["completion_percentage"] == 93.0 and b["rejection_percentage"] == 7.0

    # 13. Quality inspections (in-process fails, final passes)
    in_process = api.post("/inspections", {"batch_id": batch["id"], "inspection_type": "in_process", "parameters": [
        {"name": "Thickness mm", "expected_value": "4.0", "actual_value": "4.4", "tolerance": 0.2}]}, expect=201)
    assert in_process["result"] == "fail"
    final = api.post("/inspections", {"batch_id": batch["id"], "inspection_type": "final_product", "parameters": [
        {"name": "Thickness mm", "expected_value": "4.0", "actual_value": "4.1", "tolerance": 0.2},
        {"name": "Finish", "expected_value": "Smooth", "actual_value": "smooth"}]}, expect=201)
    assert final["result"] == "pass"
    assert api.get(f"/production/orders/{order['id']}")["approval_stage"] == "quality_inspected"

    # 14. Defects
    api.post("/defects", {"batch_id": batch["id"], "inspection_id": in_process["id"], "defect_type": "Out of tolerance",
                          "severity": "major", "quantity_affected": 4, "root_cause": "Die wear",
                          "corrective_action": "Replace die"}, expect=201)
    api.post("/defects", {"batch_id": batch["id"], "defect_type": "Crack", "severity": "critical", "quantity_affected": 3}, expect=201)

    # 15-16. Complete production and verify the inventory update
    api.post(f"/production/batches/{batch['id']}/complete", expect=200)
    assert api.get(f"/machines/{machine['id']}")["status"] == "idle"
    done = api.post(f"/production/orders/{order['id']}/complete", expect=200)
    assert done["status"] == "completed" and done["produced_quantity"] == 93
    assert api.get(f"/products/{product['id']}")["stock_quantity"] == 93
    fg = api.get("/inventory/transactions", product_id=product["id"], sort_by="id", order="asc")
    assert [(t["movement_type"], t["delta"]) for t in fg["items"]] == [("finished_goods", 93), ("rejected_goods", 0)]
    approved = api.post(f"/production/orders/{order['id']}/approve", {"comments": "signed off"}, expect=200)
    assert approved["approval_stage"] == "manager_approved"
    assert api.get("/materials/low-stock")  # X is down to 100 (> 50) but Y=100, Z=50 -> at reorder level
    assert {m["code"] for m in api.get("/materials/low-stock")} == {"RM-Z"}

    # 17. Schedule machine maintenance
    maint = api.post("/maintenance", {"machine_id": machine["id"], "maintenance_type": "preventive",
                                      "scheduled_date": str(today() + timedelta(days=5)), "description": "Die replacement"}, expect=201)
    assert maint["status"] == "scheduled"

    # 18. Dashboard
    dash = api.get("/dashboard")
    assert (dash["orders"]["total"], dash["orders"]["completed"]) == (1, 1)
    assert dash["production"]["daily_production"] == 93 and dash["production"]["rejection_rate_percent"] == 7.0
    assert dash["quality"] == {"total_inspections": 2, "passed": 1, "failed": 1, "quality_pass_percent": 50.0}
    assert dash["defects"]["total"] == 2 and dash["defects"]["by_severity"]["critical"] == 1
    assert [m["machine_code"] for m in dash["maintenance_due"]] == ["ASM-M1"]
    assert {c["material_code"]: c["consumed_quantity"] for c in dash["materials"]["consumption"]} == {"RM-X": 500, "RM-Y": 200, "RM-Z": 100}

    # 19. Reports
    daily = api.get("/reports/daily-production", plant_id=plant["id"], product_id=product["id"])
    assert daily["items"][0]["produced"] == 93 and daily["summary"]["rejection_percent"] == 7.0
    assert api.get("/reports/product-wise-production")["items"][0]["sku"] == "ASM-A"
    assert api.get("/reports/defect-analysis")["summary"]["total_defects"] == 2
    assert api.get("/reports/quality")["summary"]["pass_percent"] == 50.0
    assert api.get("/reports/worker-performance")["total"] == 3
    assert api.get("/reports/machine-performance", machine_id=machine["id"])["items"][0]["produced"] == 93
    assert api.get("/reports/material-consumption")["summary"]["total_consumed"] == 800

    # 20. Audit logs
    logs = api.get("/admin/audit-logs", size=200, sort_by="id", order="asc")["items"]
    actions = {l["action"] for l in logs}
    expected = {"user.login", "plant.create", "production_line.create", "product.create", "bom.change", "material.create",
                "material.movement", "machine.create", "worker.create", "production_order.create", "production_order.review",
                "production_order.material_check", "production_order.start", "batch.create", "batch.workers_assigned",
                "batch.start", "batch.output", "quality.inspection", "defect.create", "batch.complete", "production_order.complete",
                "production_order.approve", "maintenance.record"}
    assert expected <= actions, expected - actions
    for entry in logs:
        assert entry["user_id"] and entry["entity"] and entry["timestamp"], entry
    assert len(logs) == len({l["id"] for l in logs})
    approval = next(l for l in logs if l["action"] == "production_order.approve")
    assert approval["entity_id"] == str(order["id"])
    assert approval["previous_value"]["approval_stage"] == "production_completed"
    assert approval["new_value"]["approval_stage"] == "manager_approved"
    moves = [l for l in logs if l["action"] == "material.movement" and l["entity"] == "material" and l["entity_id"] == str(mats["RM-X"]["id"])]
    assert [m["new_value"]["available_quantity"] for m in moves] == [600, 100]  # stock-in, then batch consumption
    assert api.get("/admin/audit-logs", entity="production_order", entity_id=order["id"])["total"] >= 5
