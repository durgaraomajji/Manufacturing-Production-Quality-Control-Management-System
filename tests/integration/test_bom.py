import pytest
from pydantic import ValidationError

from app.schemas.bom import BOMCreate
from tests.helpers import create_order, make_material, make_product, setup_manufacturing


def _bom(api, product_id, items, **kw):
    return api.post("/boms", {"product_id": product_id, "items": items, **kw}, expect=201)


def test_schema_rejects_duplicate_materials_and_bad_quantities():
    with pytest.raises(ValidationError):
        BOMCreate(product_id=1, items=[{"material_id": 1, "quantity_per_unit": 1}, {"material_id": 1, "quantity_per_unit": 2}])
    with pytest.raises(ValidationError):
        BOMCreate(product_id=1, items=[{"material_id": 1, "quantity_per_unit": 0}])
    with pytest.raises(ValidationError):
        BOMCreate(product_id=1, items=[])


def test_bom_api_validation(admin):
    p = make_product(admin)
    m = make_material(admin, "M-1", 10)
    admin.error("POST", "/boms", 422, "validation_error", json={"product_id": p["id"], "items": []})
    admin.error("POST", "/boms", 422, "validation_error", json={"product_id": p["id"], "items": [
        {"material_id": m["id"], "quantity_per_unit": 1}, {"material_id": m["id"], "quantity_per_unit": 2}]})
    admin.error("POST", "/boms", 404, "not_found", json={"product_id": 999, "items": [{"material_id": m["id"], "quantity_per_unit": 1}]})
    admin.error("POST", "/boms", 404, "not_found", json={"product_id": p["id"], "items": [{"material_id": 999, "quantity_per_unit": 1}]})
    admin.patch(f"/materials/{m['id']}", {"status": "inactive"}, expect=200)
    admin.error("POST", "/boms", 422, "business_rule_violation",
                json={"product_id": p["id"], "items": [{"material_id": m["id"], "quantity_per_unit": 1}]})


def test_bom_versions_and_single_active_version(admin):
    p = make_product(admin)
    m1, m2 = make_material(admin, "M-1", 10), make_material(admin, "M-2", 10)
    v1 = _bom(admin, p["id"], [{"material_id": m1["id"], "quantity_per_unit": 5}], activate=True)
    v2 = _bom(admin, p["id"], [{"material_id": m1["id"], "quantity_per_unit": 6}, {"material_id": m2["id"], "quantity_per_unit": 1}])
    assert (v1["version"], v2["version"]) == (1, 2) and v1["is_active"] and not v2["is_active"]

    assert admin.post(f"/boms/{v2['id']}/activate", expect=200)["is_active"] is True
    assert admin.get(f"/boms/{v1['id']}")["is_active"] is False  # only one active version
    actives = admin.get("/boms", product_id=p["id"], is_active=True)
    assert actives["total"] == 1 and actives["items"][0]["id"] == v2["id"]

    assert admin.post(f"/boms/{v2['id']}/deactivate", expect=200)["is_active"] is False
    assert admin.get("/boms", product_id=p["id"], is_active=True)["total"] == 0
    assert admin.get(f"/products/{p['id']}/boms")["total"] == 2


def test_add_update_remove_materials(admin):
    p = make_product(admin)
    m1, m2 = make_material(admin, "M-1", 10), make_material(admin, "M-2", 10)
    bom = _bom(admin, p["id"], [{"material_id": m1["id"], "quantity_per_unit": 5}])

    bom = admin.post(f"/boms/{bom['id']}/items", {"material_id": m2["id"], "quantity_per_unit": 2}, expect=201)
    assert len(bom["items"]) == 2
    admin.error("POST", f"/boms/{bom['id']}/items", 409, "conflict", json={"material_id": m2["id"], "quantity_per_unit": 3})

    bom = admin.patch(f"/boms/{bom['id']}/items/{m2['id']}", {"quantity_per_unit": 4}, expect=200)
    assert {i["material_id"]: i["quantity_per_unit"] for i in bom["items"]}[m2["id"]] == 4
    admin.error("PATCH", f"/boms/{bom['id']}/items/{m2['id']}", 422, "validation_error", json={"quantity_per_unit": -1})

    bom = admin.delete(f"/boms/{bom['id']}/items/{m2['id']}", expect=200)
    assert len(bom["items"]) == 1
    admin.error("DELETE", f"/boms/{bom['id']}/items/{m1['id']}", 422, "business_rule_violation")  # last material stays
    admin.error("DELETE", f"/boms/{bom['id']}/items/999", 404, "not_found")


def test_update_bom_replaces_items(admin):
    p = make_product(admin)
    m1, m2 = make_material(admin, "M-1", 10), make_material(admin, "M-2", 10)
    bom = _bom(admin, p["id"], [{"material_id": m1["id"], "quantity_per_unit": 5}])
    updated = admin.patch(f"/boms/{bom['id']}", {"name": "Revised", "items": [{"material_id": m2["id"], "quantity_per_unit": 9}]}, expect=200)
    assert updated["name"] == "Revised" and [(i["material_id"], i["quantity_per_unit"]) for i in updated["items"]] == [(m2["id"], 9)]


def test_cannot_create_order_for_a_product_without_an_active_bom(admin):
    plant_ids = setup_manufacturing(admin)  # supplies the plant and line
    p = make_product(admin, "NO-BOM")
    order_body = {"product_id": p["id"], "quantity": 5, "target_date": "2999-01-01", "line_id": plant_ids["line"]["id"]}
    admin.error("POST", "/production/orders", 422, "business_rule_violation", json=order_body)  # no active BOM


def test_bom_is_frozen_once_used_by_an_order(admin):
    ids = setup_manufacturing(admin)
    create_order(admin, ids)
    bom_id = ids["bom"]["id"]
    admin.error("PATCH", f"/boms/{bom_id}", 409, "conflict", json={"name": "tamper"})
    admin.error("POST", f"/boms/{bom_id}/items", 409, "conflict", json={"material_id": ids["mats"]["X"]["id"], "quantity_per_unit": 1})

    v2 = admin.post(f"/boms/{bom_id}/new-version", expect=201)
    assert v2["version"] == 2 and v2["is_active"] is False
    assert [(i["material_id"], i["quantity_per_unit"]) for i in v2["items"]] == [(i["material_id"], i["quantity_per_unit"]) for i in ids["bom"]["items"]]
    admin.patch(f"/boms/{v2['id']}", {"name": "v2 edited"}, expect=200)  # the new version is editable


def test_bom_changes_are_audited(admin):
    p = make_product(admin)
    m = make_material(admin, "M-1", 10)
    bom = _bom(admin, p["id"], [{"material_id": m["id"], "quantity_per_unit": 5}])
    admin.patch(f"/boms/{bom['id']}/items/{m['id']}", {"quantity_per_unit": 7}, expect=200)
    logs = admin.get("/admin/audit-logs", entity="bom", entity_id=bom["id"], sort_by="id", order="asc")["items"]
    assert len(logs) == 2 and logs[1]["previous_value"]["items"][0]["quantity_per_unit"] == 5
    assert logs[1]["new_value"]["items"][0]["quantity_per_unit"] == 7
