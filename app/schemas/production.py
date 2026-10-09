from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, UTCDateTime
from app.utils.enums import ApprovalStage, BatchStatus, OrderPriority, OrderStatus


# ------------------------------------------------------------------ orders
class OrderCreate(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    target_date: date
    line_id: int
    priority: OrderPriority = OrderPriority.MEDIUM
    supervisor_id: int | None = None
    remarks: str | None = None


class OrderUpdate(BaseModel):
    """Only editable while the order is still a draft."""
    quantity: int | None = Field(default=None, gt=0)
    target_date: date | None = None
    line_id: int | None = None
    priority: OrderPriority | None = None
    supervisor_id: int | None = None
    remarks: str | None = None


class OrderStatusChange(BaseModel):
    """Generic status change - only pause / resume / cancel go through here.
    Scheduling, starting and completing are workflow actions with their own endpoints."""
    status: OrderStatus
    reason: str | None = Field(default=None, max_length=500)


class WorkflowAction(BaseModel):
    comments: str | None = Field(default=None, max_length=1000)


class OrderRead(ORMModel):
    id: int
    order_number: str
    product_id: int
    bom_id: int | None
    quantity: int
    target_date: date
    line_id: int
    priority: OrderPriority
    supervisor_id: int | None
    status: OrderStatus
    approval_stage: ApprovalStage
    remarks: str | None
    created_by_id: int | None
    reviewed_by_id: int | None
    reviewed_at: datetime | None
    approved_by_id: int | None
    approved_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    produced_quantity: int
    rejected_quantity: int
    completion_percentage: float
    created_at: datetime
    updated_at: datetime


class MaterialRequirement(BaseModel):
    material_id: int
    material_code: str
    material_name: str
    required_quantity: float
    available_quantity: float
    shortage: float
    sufficient: bool


class MaterialAvailability(BaseModel):
    order_id: int
    sufficient: bool
    items: list[MaterialRequirement]


class MaterialCheckResult(MaterialAvailability):
    approval_stage: ApprovalStage
    message: str


class ApprovalLogRead(ORMModel):
    id: int
    order_id: int
    from_stage: ApprovalStage | None
    to_stage: ApprovalStage
    action: str
    user_id: int | None
    comments: str | None
    created_at: datetime


# ------------------------------------------------------------------ batches
class BatchCreate(BaseModel):
    order_id: int
    planned_quantity: int = Field(gt=0)
    machine_id: int | None = None
    line_id: int | None = None  # defaults to the order's line
    supervisor_id: int | None = None  # defaults to the order's supervisor
    shift_id: int | None = None
    remarks: str | None = None


class BatchWorkersAssign(BaseModel):
    worker_ids: list[int] = Field(min_length=1)


class OutputRecord(BaseModel):
    produced: int = Field(default=0, ge=0, description="Good units produced since the last record")
    rejected: int = Field(default=0, ge=0, description="Rejected units since the last record")
    remarks: str | None = None
    recorded_at: UTCDateTime | None = None


class BatchRead(ORMModel):
    id: int
    batch_number: str
    order_id: int
    planned_quantity: int
    produced_quantity: int
    rejected_quantity: int
    start_time: datetime | None
    end_time: datetime | None
    line_id: int
    machine_id: int | None
    supervisor_id: int | None
    shift_id: int | None
    status: BatchStatus
    remarks: str | None
    completion_percentage: float
    rejection_percentage: float
    efficiency: float
    created_at: datetime


class BatchWorkerRead(ORMModel):
    id: int
    batch_id: int
    worker_id: int


class OutputLogRead(ORMModel):
    id: int
    batch_id: int
    produced: int
    rejected: int
    recorded_at: datetime
    recorded_by_id: int | None
    shift_id: int | None
    remarks: str | None
