"""Pure duty and reviewer coverage rules for assignment cases."""

from __future__ import annotations

from collections.abc import Iterable

from fdai.core.human_assignment.model import AssignmentIntent, DutyBinding, ReviewReceipt
from fdai.core.rbac.roles import Capability, Role, has_capability


class AssignmentCoverageError(ValueError):
    """Raised when duty or review coverage is insufficient."""


def normalize_principal_ref(value: str) -> str:
    """Return the comparison identity for a provider principal reference."""

    normalized = value.strip().casefold()
    if not normalized:
        raise AssignmentCoverageError("principal reference MUST be non-empty")
    return normalized


def required_review_quorum(role: Role) -> int:
    """Return the independent Owner-review count required by ``role``."""

    return 2 if role in {Role.APPROVER, Role.OWNER} else 1


def validate_duty_bindings(bindings: Iterable[DutyBinding]) -> None:
    """Reject duplicate duty slots for one target, agent, and scope."""

    seen: set[tuple[str, str]] = set()
    for binding in bindings:
        key = (binding.agent_name, binding.scope_ref.casefold())
        if key in seen:
            raise AssignmentCoverageError(
                "one subject cannot hold multiple duties for the same agent and scope"
            )
        seen.add(key)


def validate_reviewer(
    intent: AssignmentIntent,
    *,
    reviewer_ref: str,
    reviewer_roles: frozenset[Role],
    prior_reviews: tuple[ReviewReceipt, ...],
) -> None:
    """Require an eligible reviewer distinct from requester, target, and peers."""

    reviewer = normalize_principal_ref(reviewer_ref)
    excluded = {
        normalize_principal_ref(intent.requester_ref),
        normalize_principal_ref(intent.subject.subject_id),
    }
    if reviewer in excluded:
        raise AssignmentCoverageError("requester and target MUST NOT review the assignment")
    if not has_capability(reviewer_roles, Capability.MANAGE_GROUP_MEMBERSHIP):
        raise AssignmentCoverageError("assignment review requires Owner capability")
    if reviewer in {normalize_principal_ref(receipt.reviewer_ref) for receipt in prior_reviews}:
        raise AssignmentCoverageError("reviewer already decided this assignment")


def approval_quorum_satisfied(
    intent: AssignmentIntent,
    reviews: tuple[ReviewReceipt, ...],
) -> bool:
    """Return whether distinct normalized approvals satisfy the role quorum."""

    approvers = {
        normalize_principal_ref(receipt.reviewer_ref)
        for receipt in reviews
        if receipt.decision.value == "approve"
    }
    return len(approvers) >= required_review_quorum(intent.requested_role)


__all__ = [
    "AssignmentCoverageError",
    "approval_quorum_satisfied",
    "normalize_principal_ref",
    "required_review_quorum",
    "validate_duty_bindings",
    "validate_reviewer",
]
