import pytest

from app.core.exceptions import InvalidTransitionError
from app.utils.enums import ApprovalStage, OrderStatus
from app.utils.state_machine import (
    ORDER_TRANSITIONS, STAGE_FLOW, assert_order_transition, assert_stage, can_transition, next_stage,
)

S = OrderStatus


@pytest.mark.parametrize("current,new", [
    (S.DRAFT, S.SCHEDULED), (S.DRAFT, S.CANCELLED), (S.SCHEDULED, S.IN_PROGRESS), (S.SCHEDULED, S.CANCELLED),
    (S.IN_PROGRESS, S.PAUSED), (S.IN_PROGRESS, S.COMPLETED), (S.IN_PROGRESS, S.CANCELLED),
    (S.PAUSED, S.IN_PROGRESS), (S.PAUSED, S.CANCELLED),
])
def test_allowed_transitions(current, new):
    assert can_transition(current, new)
    assert_order_transition(current, new)


@pytest.mark.parametrize("current,new", [
    (S.DRAFT, S.IN_PROGRESS), (S.DRAFT, S.COMPLETED), (S.DRAFT, S.PAUSED), (S.SCHEDULED, S.COMPLETED),
    (S.SCHEDULED, S.PAUSED), (S.IN_PROGRESS, S.DRAFT), (S.IN_PROGRESS, S.SCHEDULED), (S.PAUSED, S.COMPLETED),
    (S.COMPLETED, S.IN_PROGRESS), (S.COMPLETED, S.CANCELLED), (S.CANCELLED, S.DRAFT), (S.CANCELLED, S.IN_PROGRESS),
])
def test_forbidden_transitions(current, new):
    assert not can_transition(current, new)
    with pytest.raises(InvalidTransitionError) as exc:
        assert_order_transition(current, new)
    assert current.value in str(exc.value) and new.value in str(exc.value)


def test_terminal_states_have_no_exits():
    assert ORDER_TRANSITIONS[S.COMPLETED] == set() and ORDER_TRANSITIONS[S.CANCELLED] == set()
    assert set(ORDER_TRANSITIONS) == set(OrderStatus)


def test_no_self_transitions():
    assert not any(s in targets for s, targets in ORDER_TRANSITIONS.items())


def test_approval_stages_are_linear_in_the_documented_order():
    assert [s.value for s in STAGE_FLOW] == [
        "created", "supervisor_reviewed", "material_checked", "production_started",
        "quality_inspected", "production_completed", "manager_approved"]
    assert next_stage(ApprovalStage.CREATED) == ApprovalStage.SUPERVISOR_REVIEWED
    assert next_stage(ApprovalStage.MANAGER_APPROVED) is None


def test_assert_stage_blocks_skipping_steps():
    assert_stage(ApprovalStage.CREATED, ApprovalStage.CREATED, "review")
    with pytest.raises(InvalidTransitionError):
        assert_stage(ApprovalStage.CREATED, ApprovalStage.MATERIAL_CHECKED, "start")
