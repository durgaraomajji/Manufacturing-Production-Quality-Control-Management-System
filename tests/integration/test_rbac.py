import pytest

from app.core.permissions import P, ROLE_PERMISSIONS, has_permission
from app.utils.enums import Role
from tests.helpers import create_order, make_plant, make_product, setup_manufacturing, today


def test_permission_matrix():
    assert has_permission(Role.SUPER_ADMIN, P.PLANT_WRITE) and has_permission(Role.SUPER_ADMIN, "anything:at-all")
    assert has_permission(Role.PLANT_MANAGER, P.PLANT_WRITE)
    assert not has_permission(Role.WORKER, P.PLANT_WRITE)
    assert has_permission(Role.STORE_MANAGER, P.STOCK_MOVE) and not has_permission(Role.PRODUCTION_MANAGER, P.STOCK_MOVE)
    assert has_permission(Role.QUALITY_MANAGER, P.INSPECTION_WRITE) and not has_permission(Role.PRODUCTION_MANAGER, P.INSPECTION_WRITE)
    assert has_permission(Role.MAINTENANCE_ENGINEER, P.MAINTENANCE_WRITE)
    assert set(ROLE_PERMISSIONS) == set(Role)  # every role is defined


@pytest.mark.parametrize("path", [
    "/plants", "/production-lines", "/products", "/boms", "/materials", "/machines", "/production/orders",
    "/production/batches", "/inspections", "/defects", "/maintenance", "/downtimes", "/inventory/transactions",
    "/dashboard", "/reports/daily-production", "/admin/audit-logs", "/notifications", "/users",
])
def test_every_protected_endpoint_requires_authentication(client, path):
    assert client.get(f"/api/v1{path}").status_code == 401


def test_worker_cannot_write_master_data(make_user):
    worker = make_user("worker")
    worker.error("POST", "/plants", 403, "forbidden", json={"code": "X1", "name": "Plant X"})
    worker.error("POST", "/products", 403, "forbidden", json={"sku": "S-1", "name": "Prod"})
    worker.error("GET", "/dashboard", 403, "forbidden")
    assert worker.get("/plants")["total"] == 0  # but master data is readable


def test_plant_manager_manages_plants_but_not_users(make_user):
    pm = make_user("plant_manager")
    assert pm.post("/plants", {"code": "PLT-9", "name": "Nine"}, expect=201)["code"] == "PLT-9"
    pm.error("POST", "/users", 403, json={"email": "a@b.co", "full_name": "A B", "password": "Passw0rd1", "role": "worker"})
    assert pm.get("/users")["total"] >= 1  # can list users
    assert pm.get("/admin/audit-logs")["total"] >= 1


def test_only_authorised_roles_move_stock(admin, make_user):
    ids = setup_manufacturing(admin)
    mat = ids["mats"]["X"]["id"]
    store, prod = make_user("store_manager"), make_user("production_manager")
    assert store.post(f"/materials/{mat}/stock-in", {"quantity": 5}, expect=201)["movement_type"] == "receipt"
    prod.error("POST", f"/materials/{mat}/stock-in", 403, "forbidden", json={"quantity": 5})
    prod.error("POST", f"/materials/{mat}/adjust", 403, "forbidden", json={"new_quantity": 1, "reason": "count"})


def test_order_creation_is_limited_to_production_managers(admin, make_user):
    ids = setup_manufacturing(admin)
    body = {"product_id": ids["product"]["id"], "quantity": 10, "target_date": str(today()), "line_id": ids["line"]["id"]}
    make_user("quality_manager").error("POST", "/production/orders", 403, "forbidden", json=body)
    make_user("production_supervisor").error("POST", "/production/orders", 403, "forbidden", json=body)
    assert make_user("production_manager").post("/production/orders", body, expect=201)["status"] == "draft"


def test_quality_endpoints_are_role_restricted(admin, make_user):
    ids = setup_manufacturing(admin)
    order = create_order(admin, ids)
    body = {"batch_id": 1, "inspection_type": "in_process", "parameters": [{"name": "p", "expected_value": "1", "actual_value": "1"}]}
    make_user("production_manager").error("POST", "/inspections", 403, "forbidden", json=body)
    make_user("store_manager").error("POST", "/defects", 403, "forbidden",
                                      json={"batch_id": 1, "defect_type": "x1", "severity": "minor", "quantity_affected": 1})
    assert order["status"] == "draft"


def test_approval_needs_manager_permission(admin, make_user):
    ids = setup_manufacturing(admin)
    order = create_order(admin, ids)
    make_user("quality_manager").error("POST", f"/production/orders/{order['id']}/approve", 403, "forbidden")
    make_user("worker").error("POST", f"/production/orders/{order['id']}/review", 403, "forbidden")


def test_audit_logs_restricted(make_user):
    make_user("store_manager").error("GET", "/admin/audit-logs", 403, "forbidden")
    make_user("worker").error("GET", "/admin/audit-logs", 403, "forbidden")


def test_notifications_are_private_to_their_owner(admin, make_user):
    admin.post("/admin/notifications/run-checks", expect=200)
    mine = admin.get("/notifications")
    other = make_user("worker")
    assert other.get("/notifications")["total"] == 0
    if mine["items"]:
        other.error("POST", f"/notifications/{mine['items'][0]['id']}/read", 404, "not_found")


def test_plant_and_product_helpers_exist():
    # guards the helper signatures used across the suite
    assert callable(make_plant) and callable(make_product)
