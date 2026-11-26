from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.human_assignment.coverage import (
    AssignmentCoverageError,
    approval_quorum_satisfied,
    required_review_quorum,
    validate_duty_bindings,
    validate_reviewer,
)
from fdai.core.human_assignment.model import (
    AssignmentIntent,
    DutyBinding,
    ProviderSubject,
    ReviewDecision,
    ReviewReceipt,
)
from fdai.core.rbac.roles import Role
from fdai.core.stewardship.model import Duty

NOW = datetime(2026, 8, 1, tzinfo=UTC)


def assignment_intent(role: Role) -> AssignmentIntent:
    return AssignmentIntent(
        idempotency_key="assignment-1",
        subject=ProviderSubject("entra", "target-1"),
        requested_role=role,
        duty_bindings=(DutyBinding("Odin", Duty.PRIMARY, "scope:platform"),),
        goal_refs=(),
        requester_ref="requester-1",
        justification="Assign platform ownership and bounded console access.",
    )


def review(reviewer: str) -> ReviewReceipt:
    return ReviewReceipt(reviewer, ReviewDecision.APPROVE, NOW)


def test_role_quorum_is_one_for_standard_and_two_for_elevated_roles() -> None:
    assert required_review_quorum(Role.READER) == 1
    assert required_review_quorum(Role.CONTRIBUTOR) == 1
    assert required_review_quorum(Role.APPROVER) == 2
    assert required_review_quorum(Role.OWNER) == 2
    assert approval_quorum_satisfied(assignment_intent(Role.READER), (review("owner-1"),))
    assert not approval_quorum_satisfied(
        assignment_intent(Role.OWNER),
        (review("owner-1"),),
    )
    assert approval_quorum_satisfied(
        assignment_intent(Role.OWNER),
        (review("owner-1"), review("owner-2")),
    )


@pytest.mark.parametrize("reviewer", [" REQUESTER-1 ", "TARGET-1"])
def test_no_self_approval_uses_normalized_principal_refs(reviewer: str) -> None:
    with pytest.raises(AssignmentCoverageError, match="requester and target"):
        validate_reviewer(
            assignment_intent(Role.READER),
            reviewer_ref=reviewer,
            reviewer_roles=frozenset({Role.OWNER}),
            prior_reviews=(),
        )


def test_one_subject_cannot_fill_two_duties_for_the_same_agent_scope() -> None:
    with pytest.raises(AssignmentCoverageError, match="multiple duties"):
        validate_duty_bindings(
            (
                DutyBinding("Odin", Duty.PRIMARY, "scope:platform"),
                DutyBinding("Odin", Duty.BACKUP, "SCOPE:PLATFORM"),
            )
        )
