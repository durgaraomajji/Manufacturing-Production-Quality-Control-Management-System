from tests.helpers import make_plant, make_line, make_product


def test_create_product_and_category(admin):
    cat = admin.post("/product-categories", {"name": "Gearboxes"}, expect=201)
    p = make_product(admin, "GB-100", std_time=3.5, category_id=cat["id"])
    assert p["sku"] == "GB-100" and p["status"] == "active" and p["standard_production_time"] == 3.5
    assert p["stock_quantity"] == 0 and p["category_id"] == cat["id"]
    admin.error("POST", "/product-categories", 409, "conflict", json={"name": "Gearboxes"})


def test_duplicate_sku_is_rejected_case_insensitively(admin):
    make_product(admin, "GB-100")
    admin.error("POST", "/products", 409, "conflict", json={"sku": "gb-100", "name": "Other"})


def test_product_validation(admin):
    admin.error("POST", "/products", 422, "validation_error", json={"sku": "bad sku!", "name": "Bad"})
    admin.error("POST", "/products", 422, "validation_error", json={"sku": "OK-1", "name": "P", "standard_production_time": 0})
    admin.error("POST", "/products", 422, "validation_error", json={"sku": "OK-1", "name": "Product", "status": "weird"})
    admin.error("POST", "/products", 404, "not_found", json={"sku": "OK-2", "name": "Product", "category_id": 999})


def test_product_search_filter_sort_and_pagination(admin):
    cat = admin.post("/product-categories", {"name": "Pumps"}, expect=201)
    for i in range(5):
        make_product(admin, f"PMP-{i}", category_id=cat["id"])
    make_product(admin, "VLV-1", status="inactive")

    assert admin.get("/products")["total"] == 6
    assert admin.get("/products", search="pmp")["total"] == 5
    assert admin.get("/products", status="inactive")["items"][0]["sku"] == "VLV-1"
    assert admin.get("/products", category_id=cat["id"])["total"] == 5

    page = admin.get("/products", size=2, page=3, sort_by="sku", order="asc")
    assert page["pages"] == 3 and page["size"] == 2 and [i["sku"] for i in page["items"]] == ["PMP-4", "VLV-1"]
    desc = admin.get("/products", size=2, sort_by="sku", order="desc")
    assert [i["sku"] for i in desc["items"]] == ["VLV-1", "PMP-4"]

    admin.error("GET", "/products", 422, "business_rule_violation", params={"sort_by": "nonsense"})
    admin.error("GET", "/products", 422, "validation_error", params={"size": 1000})


def test_update_and_soft_delete_product(admin):
    p = make_product(admin, "TMP-1")
    updated = admin.patch(f"/products/{p['id']}", {"name": "Renamed", "status": "discontinued"}, expect=200)
    assert updated["name"] == "Renamed" and updated["status"] == "discontinued"
    admin.delete(f"/products/{p['id']}", expect=204)
    admin.error("GET", f"/products/{p['id']}", 404, "not_found")
    assert admin.get("/products")["total"] == 0


def test_product_changes_are_audited(admin):
    p = make_product(admin, "AUD-1")
    admin.patch(f"/products/{p['id']}", {"name": "Changed"}, expect=200)
    logs = admin.get("/admin/audit-logs", entity="product", entity_id=p["id"], sort_by="id", order="asc")
    assert [l["action"] for l in logs["items"]] == ["product.create", "product.update"]
    assert logs["items"][1]["previous_value"]["name"] != logs["items"][1]["new_value"]["name"]


def test_plant_status_capacity_manager_and_lines(admin, make_user):
    plant = make_plant(admin, "PLT-7", capacity=800, address_line="1 Industrial Rd", state="MH", country="IN", postal_code="411001")
    assert plant["status"] == "active" and plant["address_line"] == "1 Industrial Rd"
    admin.error("POST", "/plants", 409, "conflict", json={"code": "PLT-7", "name": "Dup"})

    admin.patch(f"/plants/{plant['id']}/status", {"status": "maintenance", "reason": "annual overhaul"}, expect=200)
    assert admin.get(f"/plants/{plant['id']}")["status"] == "maintenance"
    admin.error("PATCH", f"/plants/{plant['id']}/status", 422, "validation_error", json={"status": "exploded"})

    manager = make_user("plant_manager")
    assert admin.put(f"/plants/{plant['id']}/manager", {"manager_id": manager.user["id"]}, expect=200)["manager_id"] == manager.user["id"]
    worker = make_user("worker")
    admin.error("PUT", f"/plants/{plant['id']}/manager", 422, "business_rule_violation", json={"manager_id": worker.user["id"]})

    # production lines: capacity, uniqueness, search, filters, pagination, supervisor validation
    sup = make_user("production_supervisor")
    line = make_line(admin, plant["id"], "LN-A", capacity=300, supervisor_id=sup.user["id"])
    assert line["supervisor_id"] == sup.user["id"] and line["status"] == "active"
    admin.error("POST", "/production-lines", 409, "conflict", json={"line_code": "LN-A", "name": "dup", "plant_id": plant["id"]})
    admin.error("POST", "/production-lines", 422, "business_rule_violation",
                json={"line_code": "LN-B", "name": "too big", "plant_id": plant["id"], "production_capacity": 5000})
    admin.error("POST", "/production-lines", 422, "business_rule_violation",
                json={"line_code": "LN-C", "name": "bad sup", "plant_id": plant["id"], "supervisor_id": worker.user["id"]})
    for i in range(4):
        make_line(admin, plant["id"], f"LN-{i}", capacity=100)
    assert admin.get("/production-lines", plant_id=plant["id"])["total"] == 5
    assert admin.get("/production-lines", search="LN-A")["total"] == 1
    assert admin.get("/production-lines", status="inactive")["total"] == 0
    assert admin.get("/production-lines", size=2, page=2)["pages"] == 3
    admin.patch(f"/production-lines/{line['id']}", {"status": "maintenance", "production_capacity": 250}, expect=200)

    admin.error("DELETE", f"/plants/{plant['id']}", 409, "conflict")  # still has lines
    for l in admin.get("/production-lines", plant_id=plant["id"], size=50)["items"]:
        admin.delete(f"/production-lines/{l['id']}", expect=204)
    admin.delete(f"/plants/{plant['id']}", expect=204)
    admin.error("GET", f"/plants/{plant['id']}", 404)


def test_plant_search_and_filters(admin):
    make_plant(admin, "PLT-A", city="Pune")
    make_plant(admin, "PLT-B", city="Chennai")
    assert admin.get("/plants", search="chennai")["total"] == 1
    assert admin.get("/plants", city="Pune")["items"][0]["code"] == "PLT-A"
