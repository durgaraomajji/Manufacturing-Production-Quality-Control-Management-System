"""Role -> permission matrix (RBAC).

Endpoints declare the permission they need via `require_permission(P.X)` (see app/api/deps.py).
Super Admin holds the wildcard "*".
"""
from app.utils.enums import Role


class P:
    # users
    USER_READ = "user:read"
    USER_MANAGE = "user:manage"
    # master data
    MASTER_READ = "master:read"
    PLANT_READ = "plant:read"
    PLANT_WRITE = "plant:write"
    LINE_WRITE = "line:write"
    PRODUCT_WRITE = "product:write"
    BOM_WRITE = "bom:write"
    MACHINE_WRITE = "machine:write"
    MACHINE_STATUS = "machine:status"
    WORKER_WRITE = "worker:write"
    SHIFT_WRITE = "shift:write"
    # materials / inventory
    MATERIAL_READ = "material:read"
    MATERIAL_WRITE = "material:write"
    STOCK_MOVE = "stock:move"
    INVENTORY_READ = "inventory:read"
    INVENTORY_ADJUST = "inventory:adjust"
    # production
    ORDER_CREATE = "order:create"
    ORDER_REVIEW = "order:review"
    ORDER_EXECUTE = "order:execute"
    ORDER_MANAGE = "order:manage"
    ORDER_APPROVE = "order:approve"
    # quality
    INSPECTION_WRITE = "inspection:write"
    DEFECT_WRITE = "defect:write"
    # maintenance
    MAINTENANCE_WRITE = "maintenance:write"
    DOWNTIME_WRITE = "downtime:write"
    # analytics / admin
    REPORT_READ = "report:read"
    AUDIT_READ = "audit:read"
    NOTIFICATION_MANAGE = "notification:manage"


_SA, _PL, _PM, _QM, _ME, _SM, _SU, _WK = (
    Role.SUPER_ADMIN, Role.PLANT_MANAGER, Role.PRODUCTION_MANAGER, Role.QUALITY_MANAGER,
    Role.MAINTENANCE_ENGINEER, Role.STORE_MANAGER, Role.PRODUCTION_SUPERVISOR, Role.WORKER,
)

# permission -> roles allowed (Super Admin is always allowed via wildcard)
_PERMISSION_ROLES: dict[str, set[Role]] = {
    P.USER_READ: {_PL},
    P.USER_MANAGE: set(),
    P.MASTER_READ: set(Role),
    P.PLANT_READ: set(Role),
    P.PLANT_WRITE: {_PL},
    P.LINE_WRITE: {_PL, _PM},
    P.PRODUCT_WRITE: {_PL, _PM},
    P.BOM_WRITE: {_PM},
    P.MACHINE_WRITE: {_PL, _PM, _ME},
    P.MACHINE_STATUS: {_PL, _PM, _ME, _SU},
    P.WORKER_WRITE: {_PL, _PM, _SU},
    P.SHIFT_WRITE: {_PL, _PM},
    P.MATERIAL_READ: {_PL, _PM, _QM, _ME, _SM, _SU},
    P.MATERIAL_WRITE: {_SM},
    P.STOCK_MOVE: {_SM},
    P.INVENTORY_READ: {_PL, _PM, _QM, _SM, _SU},
    P.INVENTORY_ADJUST: {_SM},
    P.ORDER_CREATE: {_PM},
    P.ORDER_REVIEW: {_PM, _SU},
    P.ORDER_EXECUTE: {_PM, _SU},
    P.ORDER_MANAGE: {_PM},
    P.ORDER_APPROVE: {_PM, _PL},
    P.INSPECTION_WRITE: {_QM},
    P.DEFECT_WRITE: {_QM, _PM, _SU},
    P.MAINTENANCE_WRITE: {_PL, _ME},
    P.DOWNTIME_WRITE: {_PL, _PM, _ME, _SU},
    P.REPORT_READ: {_PL, _PM, _QM, _ME, _SM, _SU},
    P.AUDIT_READ: {_PL},
    P.NOTIFICATION_MANAGE: {_PL, _PM},
}

ROLE_PERMISSIONS: dict[Role, set[str]] = {
    role: {perm for perm, roles in _PERMISSION_ROLES.items() if role in roles} for role in Role
}
ROLE_PERMISSIONS[Role.SUPER_ADMIN] = {"*"}


def has_permission(role: Role | str, permission: str) -> bool:
    perms = ROLE_PERMISSIONS.get(Role(role), set())
    return "*" in perms or permission in perms
