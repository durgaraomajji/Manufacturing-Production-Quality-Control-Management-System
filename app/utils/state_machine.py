"""Production-order status transitions (Level 8) and approval-stage flow (Level 17)."""
from app.core.exceptions import InvalidTransitionError
from app.utils.enums import ApprovalStage, OrderStatus

ORDER_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.DRAFT: {OrderStatus.SCHEDULED, OrderStatus.CANCELLED},
    OrderStatus.SCHEDULED: {OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED},
    OrderStatus.IN_PROGRESS: {OrderStatus.PAUSED, OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    OrderStatus.PAUSED: {OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
}

# Linear workflow: created -> supervisor review -> material check -> start -> quality -> completion -> approval
STAGE_FLOW: list[ApprovalStage] = list(ApprovalStage)


def can_transition(current: OrderStatus, new: OrderStatus) -> bool:
    return new in ORDER_TRANSITIONS.get(current, set())


def assert_order_transition(current: OrderStatus, new: OrderStatus) -> None:
    if not can_transition(current, new):
        allowed = sorted(s.value for s in ORDER_TRANSITIONS.get(current, set())) or ["none (terminal state)"]
        raise InvalidTransitionError(
            f"Cannot move order from '{current.value}' to '{new.value}'. Allowed: {', '.join(allowed)}"
        )


def next_stage(stage: ApprovalStage) -> ApprovalStage | None:
    idx = STAGE_FLOW.index(stage)
    return STAGE_FLOW[idx + 1] if idx + 1 < len(STAGE_FLOW) else None


def stage_index(stage: ApprovalStage) -> int:
    return STAGE_FLOW.index(stage)


def assert_stage(current: ApprovalStage, expected: ApprovalStage, action: str) -> None:
    """The workflow only moves forward one step at a time: `action` requires the order to be at `expected`."""
    if current != expected:
        raise InvalidTransitionError(
            f"Cannot {action}: order is at stage '{current.value}' but must be at '{expected.value}'"
        )
