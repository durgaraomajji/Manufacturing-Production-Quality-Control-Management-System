from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, UTCDateTime
from app.utils.enums import InspectionResult, InspectionType, ResolutionStatus, Severity


class ParameterIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    expected_value: str = Field(max_length=100)
    actual_value: str = Field(max_length=100)
    tolerance: float | None = Field(default=None, ge=0, description="Allowed |actual - expected| for numeric values")
    passed: bool | None = Field(default=None, description="Explicit verdict; derived from values when omitted")
    remarks: str | None = None


class InspectionCreate(BaseModel):
    batch_id: int
    inspection_type: InspectionType
    material_id: int | None = Field(default=None, description="For incoming material inspections")
    inspection_date: UTCDateTime | None = None
    parameters: list[ParameterIn] = Field(min_length=1)
    remarks: str | None = None


class ParameterRead(ORMModel):
    id: int
    name: str
    expected_value: str
    actual_value: str
    tolerance: float | None
    passed: bool
    remarks: str | None


class InspectionRead(ORMModel):
    id: int
    batch_id: int
    inspection_type: InspectionType
    inspector_id: int
    material_id: int | None
    inspection_date: datetime
    result: InspectionResult
    remarks: str | None
    parameters: list[ParameterRead]
    created_at: datetime


class DefectCreate(BaseModel):
    batch_id: int
    product_id: int | None = Field(default=None, description="Defaults to the batch's product")
    inspection_id: int | None = None
    defect_type: str = Field(min_length=2, max_length=100)
    severity: Severity
    quantity_affected: int = Field(gt=0)
    description: str | None = None
    root_cause: str | None = None
    corrective_action: str | None = None


class DefectUpdate(BaseModel):
    defect_type: str | None = Field(default=None, min_length=2, max_length=100)
    severity: Severity | None = None
    quantity_affected: int | None = Field(default=None, gt=0)
    description: str | None = None
    root_cause: str | None = None
    corrective_action: str | None = None
    resolution_status: ResolutionStatus | None = None


class DefectRead(ORMModel):
    id: int
    batch_id: int
    product_id: int
    inspection_id: int | None
    defect_type: str
    severity: Severity
    quantity_affected: int
    description: str | None
    root_cause: str | None
    corrective_action: str | None
    resolution_status: ResolutionStatus
    reported_by_id: int | None
    resolved_at: datetime | None
    created_at: datetime
