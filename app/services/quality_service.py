"""Quality inspections and defect management (Levels 12 and 13)."""
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, InvalidTransitionError, NotFoundError
from app.models.material import Material
from app.models.quality import Defect, Inspection, InspectionParameter
from app.models.user import User
from app.repositories.production import batch_repo
from app.repositories.quality import defect_repo, inspection_repo
from app.services import audit_service, notification_service, production_service
from app.utils.dt import utcnow
from app.utils.enums import (
    ApprovalStage, AuditAction, BatchStatus, InspectionResult, InspectionType, NotificationType,
    ResolutionStatus, Severity,
)

DEFECT_TRANSITIONS: dict[ResolutionStatus, set[ResolutionStatus]] = {
    ResolutionStatus.OPEN: {ResolutionStatus.IN_PROGRESS, ResolutionStatus.RESOLVED},
    ResolutionStatus.IN_PROGRESS: {ResolutionStatus.OPEN, ResolutionStatus.RESOLVED},
    ResolutionStatus.RESOLVED: {ResolutionStatus.IN_PROGRESS, ResolutionStatus.CLOSED},
    ResolutionStatus.CLOSED: set(),
}


def evaluate_parameter(expected: str, actual: str, tolerance: float | None, passed: bool | None) -> bool:
    """Verdict for one inspection parameter.
    Explicit `passed` wins. Otherwise numeric values pass when |actual-expected| <= tolerance (default 0);
    non-numeric values pass when they match case-insensitively."""
    if passed is not None:
        return passed
    try:
        return abs(float(actual) - float(expected)) <= (tolerance or 0.0) + 1e-9
    except ValueError:
        return expected.strip().lower() == actual.strip().lower()


def create_inspection(db: Session, data: dict, user: User) -> Inspection:
    batch = batch_repo.get_or_404(db, data["batch_id"])
    if batch.status == BatchStatus.CANCELLED:
        raise BusinessRuleError("Cannot inspect a cancelled batch")
    itype: InspectionType = data["inspection_type"]
    order = batch.order
    if itype in (InspectionType.IN_PROCESS, InspectionType.FINAL_PRODUCT) and batch.status == BatchStatus.PLANNED:
        raise BusinessRuleError("Production has not started for this batch; only incoming material inspections are possible")
    if itype == InspectionType.FINAL_PRODUCT and batch.produced_quantity + batch.rejected_quantity == 0:
        raise BusinessRuleError("Record production output before the final product inspection")
    if data.get("material_id") is not None:
        material = db.get(Material, data["material_id"])
        if material is None or material.is_deleted:
            raise NotFoundError("Material", data["material_id"])
    elif itype == InspectionType.INCOMING_MATERIAL:
        raise BusinessRuleError("Incoming material inspections must reference a material_id")

    params = [InspectionParameter(
        name=p["name"], expected_value=p["expected_value"], actual_value=p["actual_value"], tolerance=p.get("tolerance"),
        passed=evaluate_parameter(p["expected_value"], p["actual_value"], p.get("tolerance"), p.get("passed")),
        remarks=p.get("remarks")) for p in data["parameters"]]
    result = InspectionResult.PASS if all(p.passed for p in params) else InspectionResult.FAIL
    inspection = inspection_repo.create(db, {
        "batch_id": batch.id, "inspection_type": itype, "inspector_id": user.id, "material_id": data.get("material_id"),
        "inspection_date": data.get("inspection_date") or utcnow(), "result": result, "remarks": data.get("remarks"),
    })
    for p in params:
        inspection.parameters.append(p)
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.INSPECTION, entity="inspection", entity_id=inspection.id,
                      new={"batch_id": batch.id, "type": itype.value, "result": result.value,
                           "failed_parameters": [p.name for p in params if not p.passed]})
    if itype == InspectionType.FINAL_PRODUCT and result == InspectionResult.PASS:
        production_service.on_final_inspection_passed(db, order, user)
    return inspection


def create_defect(db: Session, data: dict, user: User) -> Defect:
    batch = batch_repo.get_or_404(db, data["batch_id"])
    if batch.status == BatchStatus.PLANNED:
        raise BusinessRuleError("Defects can only be logged for batches that have started production")
    product_id = data.get("product_id") or batch.order.product_id
    if product_id != batch.order.product_id:
        raise BusinessRuleError("Product does not match the batch's product")
    if data["quantity_affected"] > batch.planned_quantity:
        raise BusinessRuleError(f"Quantity affected exceeds the batch quantity ({batch.planned_quantity})")
    if data.get("inspection_id") is not None:
        insp = inspection_repo.get_or_404(db, data["inspection_id"])
        if insp.batch_id != batch.id:
            raise BusinessRuleError("Inspection belongs to a different batch")
    defect = defect_repo.create(db, {**data, "product_id": product_id, "reported_by_id": user.id,
                                     "resolution_status": ResolutionStatus.OPEN})
    audit_service.log(db, user_id=user.id, action=AuditAction.DEFECT_CREATE, entity="defect", entity_id=defect.id,
                      new=audit_service.snapshot(defect))
    if defect.severity == Severity.CRITICAL:
        notification_service.notify(
            db, NotificationType.CRITICAL_DEFECT, f"Critical defect on {batch.batch_number}",
            f"{defect.defect_type}: {defect.quantity_affected} unit(s) affected. {defect.description or ''}".strip(),
            severity="critical", entity_type="defect", entity_id=defect.id, dedupe_key=f"critical_defect:{defect.id}")
    return defect


def update_defect(db: Session, defect: Defect, data: dict, user: User) -> Defect:
    new_status = data.get("resolution_status")
    if new_status is not None and new_status != defect.resolution_status:
        if new_status not in DEFECT_TRANSITIONS[defect.resolution_status]:
            allowed = sorted(s.value for s in DEFECT_TRANSITIONS[defect.resolution_status]) or ["none"]
            raise InvalidTransitionError(
                f"Cannot move defect from '{defect.resolution_status.value}' to '{new_status.value}'. Allowed: {', '.join(allowed)}")
        corrective = data.get("corrective_action", defect.corrective_action)
        if new_status in (ResolutionStatus.RESOLVED, ResolutionStatus.CLOSED) and not corrective:
            raise BusinessRuleError("A corrective action is required before a defect can be resolved")
    if "quantity_affected" in data and data["quantity_affected"] > defect_batch_quantity(db, defect):
        raise BusinessRuleError("Quantity affected exceeds the batch quantity")
    previous = audit_service.snapshot(defect)
    defect_repo.update(db, defect, data)
    if new_status == ResolutionStatus.RESOLVED:
        defect.resolved_at = utcnow()
    elif new_status in (ResolutionStatus.OPEN, ResolutionStatus.IN_PROGRESS):
        defect.resolved_at = None
    db.flush()
    audit_service.log(db, user_id=user.id, action=AuditAction.DEFECT_UPDATE, entity="defect", entity_id=defect.id,
                      previous=previous, new=audit_service.snapshot(defect))
    return defect


def defect_batch_quantity(db: Session, defect: Defect) -> int:
    return batch_repo.get_or_404(db, defect.batch_id).planned_quantity
