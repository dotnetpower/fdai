"""Approval profiles and the never-raising operator policy input.

Operator Governance Profiles (docs/roadmap/decisioning/operator-governance-profiles.md)
defines two production approval profiles:

- ``multi-operator`` (default): distinct humans approve, the requester is
  ineligible, and the original quorum applies.
- ``single-operator-production``: one named operator satisfies every
  requester, approver, reviewer, and quorum requirement. The audit records the
  original quorum and an effective quorum of one.

Neither profile changes a risk class, A4 denial, the seven safeguards, or the
separation of the approval principal (Var) from the executor (Thor). This
module is pure: it reduces only the *number* of human approvals a HIL decision
needs and never raises an autonomy level.

The operator policy input models the outcome of installation approval or
admission policy. Core combines it with ``min()`` after the constitutional
ceiling, so an operator revision can only lower autonomy and never relaxes a
hard constraint.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fdai_service_contracts.approval_profile import (
    ApprovalProfileDecision,
    ApprovalProfileKind,
    ApprovalProfileRefusal,
    ApprovalProfileRevision,
    approval_profile_from_audit_dict,
    approval_profile_policy_digest,
    effective_quorum_for,
    evaluate_profile_approval,
    profile_transition_quorum,
)

from fdai.core.risk_gate.ceiling import AxisLevel

_DIGEST_PREFIX = "sha256:"
_DIGEST_LENGTH = len(_DIGEST_PREFIX) + 64


def _require_digest(value: str, field_name: str) -> None:
    lowered = value.lower()
    if (
        len(value) != _DIGEST_LENGTH
        or not lowered.startswith(_DIGEST_PREFIX)
        or any(ch not in "0123456789abcdef" for ch in lowered[len(_DIGEST_PREFIX) :])
        or value != lowered
    ):
        raise ValueError(f"{field_name} MUST be a lowercase sha256 digest")


class OperatorPolicyOutcome(StrEnum):
    """Installation approval or admission policy outcome for one ActionType."""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


_OPERATOR_OUTCOME_LEVEL: dict[OperatorPolicyOutcome, AxisLevel] = {
    OperatorPolicyOutcome.ALLOW: AxisLevel.ENFORCE_AUTO,
    OperatorPolicyOutcome.REQUIRE_APPROVAL: AxisLevel.ENFORCE_HIL,
    OperatorPolicyOutcome.DENY: AxisLevel.DENY,
}


@dataclass(frozen=True, slots=True)
class OperatorPolicyInput:
    """One evaluated operator policy decision, pinned to its revision digest.

    The pinned digest lets a replay reproduce an in-flight decision even after a
    newer revision is activated.
    """

    revision_id: str
    policy_digest: str
    outcome: OperatorPolicyOutcome

    def __post_init__(self) -> None:
        if not self.revision_id.strip():
            raise ValueError("operator policy revision_id MUST be non-empty")
        _require_digest(self.policy_digest, "operator policy policy_digest")

    @property
    def level(self) -> AxisLevel:
        return _OPERATOR_OUTCOME_LEVEL[self.outcome]

    def as_audit_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "policy_digest": self.policy_digest,
            "outcome": self.outcome.value,
        }


def apply_operator_policy(
    constitutional_level: AxisLevel,
    operator_policy: OperatorPolicyInput | None,
) -> AxisLevel:
    """Combine operator policy with the constitutional ceiling, never raising it."""

    if operator_policy is None:
        return constitutional_level
    return min(constitutional_level, operator_policy.level)


__all__ = [
    "ApprovalProfileDecision",
    "ApprovalProfileKind",
    "ApprovalProfileRefusal",
    "ApprovalProfileRevision",
    "OperatorPolicyInput",
    "OperatorPolicyOutcome",
    "approval_profile_from_audit_dict",
    "approval_profile_policy_digest",
    "apply_operator_policy",
    "effective_quorum_for",
    "evaluate_profile_approval",
    "profile_transition_quorum",
]
