"""Domain enumerations. Values are stored as lowercase strings (VARCHAR) for portability."""
from enum import StrEnum


class Role(StrEnum):
    SUPER_ADMIN = "super_admin"
    PLANT_MANAGER = "plant_manager"
    PRODUCTION_MANAGER = "production_manager"
    QUALITY_MANAGER = "quality_manager"
    MAINTENANCE_ENGINEER = "maintenance_engineer"
    STORE_MANAGER = "store_manager"
    PRODUCTION_SUPERVISOR = "production_supervisor"
    WORKER = "worker"


class PlantStatus(StrEnum):
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    TEMPORARILY_CLOSED = "temporarily_closed"
    INACTIVE = "inactive"


class LineStatus(StrEnum):
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    INACTIVE = "inactive"


class ProductStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DISCONTINUED = "discontinued"


class MaterialStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DISCONTINUED = "discontinued"


class MachineStatus(StrEnum):
    RUNNING = "running"
    IDLE = "idle"
    MAINTENANCE = "maintenance"
    BREAKDOWN = "breakdown"
    DECOMMISSIONED = "decommissioned"


class OrderStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class OrderPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class ApprovalStage(StrEnum):
    """Approval workflow (Level 17). Stages are strictly linear."""
    CREATED = "created"
    SUPERVISOR_REVIEWED = "supervisor_reviewed"
    MATERIAL_CHECKED = "material_checked"
    PRODUCTION_STARTED = "production_started"
    QUALITY_INSPECTED = "quality_inspected"
    PRODUCTION_COMPLETED = "production_completed"
    MANAGER_APPROVED = "manager_approved"


class BatchStatus(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkerStatus(StrEnum):
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    INACTIVE = "inactive"


class ShiftName(StrEnum):
    MORNING = "morning"
    EVENING = "evening"
    NIGHT = "night"


class InspectionType(StrEnum):
    INCOMING_MATERIAL = "incoming_material"
    IN_PROCESS = "in_process"
    FINAL_PRODUCT = "final_product"


class InspectionResult(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class Severity(StrEnum):
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class ResolutionStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class MaintenanceType(StrEnum):
    PREVENTIVE = "preventive"
    BREAKDOWN = "breakdown"


class MaintenanceStatus(StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DowntimeCategory(StrEnum):
    MACHINE_BREAKDOWN = "machine_breakdown"
    MATERIAL_SHORTAGE = "material_shortage"
    QUALITY_ISSUE = "quality_issue"
    POWER_FAILURE = "power_failure"
    MAINTENANCE = "maintenance"
    OPERATOR_ISSUE = "operator_issue"


class MovementType(StrEnum):
    RECEIPT = "receipt"                  # raw material received (stock-in)
    CONSUMPTION = "consumption"          # raw material consumed by production
    STOCK_OUT = "stock_out"              # manual material issue
    FINISHED_GOODS = "finished_goods"    # finished goods produced
    REJECTED_GOODS = "rejected_goods"    # rejected output (logged, no stock change)
    ADJUSTMENT = "adjustment"            # stock correction


class NotificationType(StrEnum):
    LOW_STOCK = "low_stock"
    PRODUCTION_DEADLINE = "production_deadline"
    MACHINE_BREAKDOWN = "machine_breakdown"
    MAINTENANCE_DUE = "maintenance_due"
    CRITICAL_DEFECT = "critical_defect"
    HIGH_REJECTION = "high_rejection"
    PRODUCTION_DELAY = "production_delay"
    APPROVAL_PENDING = "approval_pending"


class AuditAction(StrEnum):
    USER_LOGIN = "user.login"
    USER_CREATE = "user.create"
    USER_UPDATE = "user.update"
    PLANT_CREATE = "plant.create"
    PLANT_UPDATE = "plant.update"
    LINE_CREATE = "production_line.create"
    LINE_UPDATE = "production_line.update"
    PRODUCT_CREATE = "product.create"
    PRODUCT_UPDATE = "product.update"
    BOM_CHANGE = "bom.change"
    ORDER_CREATE = "production_order.create"
    ORDER_REVIEW = "production_order.review"
    ORDER_MATERIAL_CHECK = "production_order.material_check"
    ORDER_START = "production_order.start"
    ORDER_STATUS = "production_order.status_change"
    ORDER_COMPLETE = "production_order.complete"
    ORDER_APPROVE = "production_order.approve"
    BATCH_CREATE = "batch.create"
    BATCH_START = "batch.start"
    BATCH_OUTPUT = "batch.output"
    BATCH_COMPLETE = "batch.complete"
    MATERIAL_MOVEMENT = "material.movement"
    INVENTORY_ADJUSTMENT = "inventory.adjustment"
    INSPECTION = "quality.inspection"
    DEFECT_CREATE = "defect.create"
    DEFECT_UPDATE = "defect.update"
    MACHINE_STATUS = "machine.status_change"
    MACHINE_CREATE = "machine.create"
    MAINTENANCE = "maintenance.record"
    DOWNTIME = "downtime.record"
