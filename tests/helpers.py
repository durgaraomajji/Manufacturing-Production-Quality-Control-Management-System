"""Small API wrapper + scenario builders shared by the tests."""
from datetime import timedelta

from app.utils.dt import utcnow

API = "/api/v1"


def today():
    return utcnow().date()


class Api:
    """Thin wrapper around TestClient that carries auth headers and asserts status codes."""

    def __init__(self, client, headers=None):
        self.c, self.h = client, headers or {}
        self.user = None

    def req(self, method, path, expect=None, **kw):
        r = self.c.request(method, API + path, headers=self.h, **kw)
        if expect is None:
            assert r.status_code < 300, f"{method} {path} -> {r.status_code}: {r.text}"
        elif r.status_code != expect:
            raise AssertionError(f"{method} {path} expected {expect} got {r.status_code}: {r.text}")
        return r

    def _json(self, r):
        return r.json() if r.content else None

    def get(self, path, expect=None, **params):
        return self._json(self.req("GET", path, expect, params={k: v for k, v in params.items() if v is not None}))

    def post(self, path, json=None, expect=None):
        return self._json(self.req("POST", path, expect, json=json))

    def patch(self, path, json=None, expect=None):
        return self._json(self.req("PATCH", path, expect, json=json))

    def put(self, path, json=None, expect=None):
        return self._json(self.req("PUT", path, expect, json=json))

    def delete(self, path, expect=None):
        return self._json(self.req("DELETE", path, expect))

    def raw(self, method, path, **kw):
        """No status assertion - returns the response."""
        return self.c.request(method, API + path, headers=self.h, **kw)

    def error(self, method, path, status, code=None, **kw):
        r = self.raw(method, path, **kw)
        assert r.status_code == status, f"{method} {path} expected {status} got {r.status_code}: {r.text}"
        body = r.json()
        assert "error" in body, body
        if code:
            assert body["error"]["code"] == code, body
        return body["error"]


# ---------------------------------------------------------------- master data builders
def make_plant(api, code="PLT-1", capacity=1000, **kw):
    return api.post("/plants", {"code": code, "name": f"Plant {code}", "production_capacity": capacity, "city": "Pune", **kw}, expect=201)


def make_line(api, plant_id, code="LN-1", capacity=500, **kw):
    return api.post("/production-lines", {"line_code": code, "name": f"Line {code}", "plant_id": plant_id,
                                          "production_capacity": capacity, **kw}, expect=201)


def make_product(api, sku="SKU-A", std_time=2.0, **kw):
    return api.post("/products", {"sku": sku, "name": f"Product {sku}", "standard_production_time": std_time,
                                  "unit_of_measure": "pcs", **kw}, expect=201)


def make_material(api, code, qty, minimum=0, reorder=0, **kw):
    return api.post("/materials", {"code": code, "name": f"Material {code}", "unit": "kg", "initial_quantity": qty,
                                   "minimum_stock_level": minimum, "reorder_level": reorder, **kw}, expect=201)


def make_machine(api, line_id, code="MC-1", **kw):
    return api.post("/machines", {"machine_code": code, "name": f"Machine {code}", "machine_type": "CNC", "line_id": line_id, **kw}, expect=201)


def make_worker(api, code, line_id=None, **kw):
    return api.post("/production/workers", {"employee_code": code, "full_name": f"Worker {code}", "skill": "assembly",
                                            "department": "assembly", "line_id": line_id, **kw}, expect=201)


# ---------------------------------------------------------------- scenario builders
def setup_manufacturing(api, bom_qty=(5, 2, 1), stock=(1000, 500, 300)):
    """Plant, line, product, 3 materials, an active BOM (Product A: X x5, Y x2, Z x1), a machine and 2 workers."""
    plant = make_plant(api)
    line = make_line(api, plant["id"])
    product = make_product(api)
    mats = {name: make_material(api, f"MAT-{name}", qty, minimum=10) for name, qty in zip("XYZ", stock)}
    bom = api.post("/boms", {"product_id": product["id"], "name": "Product A BOM", "activate": True, "items": [
        {"material_id": mats[n]["id"], "quantity_per_unit": q} for n, q in zip("XYZ", bom_qty)]}, expect=201)
    machine = make_machine(api, line["id"])
    workers = [make_worker(api, "EMP-1", line["id"]), make_worker(api, "EMP-2", line["id"])]
    return {"plant": plant, "line": line, "product": product, "mats": mats, "bom": bom, "machine": machine, "workers": workers}


def create_order(api, ids, qty=50, days=5, **kw):
    return api.post("/production/orders", {
        "product_id": ids["product"]["id"], "quantity": qty, "target_date": str(today() + timedelta(days=days)),
        "line_id": ids["line"]["id"], "priority": "high", **kw}, expect=201)


def to_material_checked(api, ids, qty=50):
    order = create_order(api, ids, qty)
    api.post(f"/production/orders/{order['id']}/review", expect=200)
    result = api.post(f"/production/orders/{order['id']}/check-materials", expect=200)
    assert result["sufficient"] is True
    return order


def make_batch(api, ids, order, planned=50, workers=True, machine=True):
    batch = api.post("/production/batches", {
        "order_id": order["id"], "planned_quantity": planned,
        "machine_id": ids["machine"]["id"] if machine else None}, expect=201)
    if workers:
        api.post(f"/production/batches/{batch['id']}/workers", {"worker_ids": [w["id"] for w in ids["workers"]]}, expect=201)
    return batch


def final_inspection(api, batch_id, expected="10", actual="10", **kw):
    return api.post("/inspections", {"batch_id": batch_id, "inspection_type": "final_product", "parameters": [
        {"name": "Length", "expected_value": expected, "actual_value": actual, "tolerance": 0.5}], **kw}, expect=201)


def run_full_flow(api, ids=None, qty=50, produced=48, rejected=2):
    """The mandatory end-to-end scenario, up to manager approval. Returns the ids it created."""
    ids = ids or setup_manufacturing(api)
    order = to_material_checked(api, ids, qty)
    batch = make_batch(api, ids, order, planned=qty)
    api.post(f"/production/batches/{batch['id']}/start", expect=200)
    api.post(f"/production/batches/{batch['id']}/output", {"produced": produced, "rejected": rejected}, expect=200)
    inspection = final_inspection(api, batch["id"])
    defect = None
    if rejected:
        defect = api.post("/defects", {"batch_id": batch["id"], "defect_type": "Scratch", "severity": "minor",
                                       "quantity_affected": rejected, "root_cause": "Tool wear"}, expect=201)
    api.post(f"/production/batches/{batch['id']}/complete", expect=200)
    api.post(f"/production/orders/{order['id']}/complete", expect=200)
    order = api.post(f"/production/orders/{order['id']}/approve", expect=200)
    return {**ids, "order": order, "batch": batch, "inspection": inspection, "defect": defect}
