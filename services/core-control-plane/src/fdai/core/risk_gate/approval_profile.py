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

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from fdai.core.risk_gate.ceiling import AxisLevel

_DIGEST_PREFIX = "sha256:"
_DIGEST_LENGTH = len(_DIGEST_PREFIX) + 64


class ApprovalProfileKind(StrEnum):
    """Production approval profile selected by an approval policy revision."""

    MULTI_OPERATOR = "multi-operator"
    SINGLE_OPERATOR_PRODUCTION = "single-operator-production"


class ApprovalProfileRefusal(StrEnum):
    """Why an approval is refused under the active approval profile."""

    BLANK_APPROVER = "blank_approver"
    UNKNOWN_REQUESTER = "unknown_requester"
    SELF_APPROVAL = "self_approval"
    UNNAMED_PRINCIPAL = "unnamed_principal"
    APPROVER_IS_EXECUTOR = "approver_is_executor"


def _normalized(value: str) -> str:
    return value.strip().casefold()


def _require_digest(value: str, field_name: str) -> None:
    lowered = value.lower()
    if (
        len(value) != _DIGEST_LENGTH
        or not lowered.startswith(_DIGEST_PREFIX)
        or any(ch not in "0123456789abcdef" for ch in lowered[len(_DIGEST_PREFIX) :])
        or value != lowered
    ):
        raise ValueError(f"{field_name} MUST be a lowercase sha256 digest")


@dataclass(frozen=True, slots=True)
class ApprovalProfileRevision:
    """One immutable approval policy revision that selects a profile.

    ``operator_principal`` is the normalized Microsoft Entra ID principal of the
    named installation operator. It is required for the single-operator
    production profile and forbidden for the multi-operator profile.
    ``executor_principal`` is the Thor execution identity, which the operator
    must never be.
    """

    revision_id: str
    approval_profile: ApprovalProfileKind
    executor_principal: str
    policy_digest: str
    effective_from: datetime
    operator_principal: str | None = None

    def __post_init__(self) -> None:
        if not self.revision_id.strip():
            raise ValueError("approval profile revision_id MUST be non-empty")
        if not self.executor_principal.strip():
            raise ValueError("approval profile executor_principal MUST be non-empty")
        _require_digest(self.policy_digest, "approval profile policy_digest")
        if self.effective_from.tzinfo is None:
            raise ValueError("approval profile effective_from MUST be timezone-aware")
        operator = (self.operator_principal or "").strip()
        if self.approval_profile is ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION:
            if not operator:
                raise ValueError("single-operator-production MUST name one operator principal")
            if _normalized(operator) == _normalized(self.executor_principal):
                raise ValueError("the named operator MUST NOT be the executor principal")
        elif self.operator_principal is not None:
            raise ValueError("multi-operator profile MUST NOT name an operator principal")

    @property
    def is_single_operator(self) -> bool:
        return self.approval_profile is ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION

    def names(self, principal: str) -> bool:
        """Return whether ``principal`` is the named single operator."""

        return (
            self.is_single_operator
            and self.operator_principal is not None
            and bool(principal.strip())
            and _normalized(principal) == _normalized(self.operator_principal)
        )

    def as_audit_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "approval_profile": self.approval_profile.value,
            "operator_principal": self.operator_principal,
            "executor_principal": self.executor_principal,
            "policy_digest": self.policy_digest,
            "effective_from": self.effective_from.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ApprovalProfileDecision:
    """Whether one human approval satisfies the active approval profile."""

    allowed: bool
    approval_profile: ApprovalProfileKind
    original_quorum: int
    effective_quorum: int
    refusal: ApprovalProfileRefusal | None = None
    operator_principal: str | None = None
    self_review: bool = False

    def as_audit_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "approval_profile": self.approval_profile.value,
            "original_quorum": self.original_quorum,
            "effective_quorum": self.effective_quorum,
            "refusal": None if self.refusal is None else self.refusal.value,
            "operator_principal": self.operator_principal,
            "self_review": self.self_review,
        }


def effective_quorum_for(profile: ApprovalProfileRevision | None, original_quorum: int) -> int:
    """Return the number of approvals the active profile requires."""

    if isinstance(original_quorum, bool) or original_quorum < 1:
        raise ValueError("original quorum MUST be an integer >= 1")
    if profile is not None and profile.is_single_operator:
        return 1
    return original_quorum


def evaluate_profile_approval(
    profile: ApprovalProfileRevision | None,
    *,
    approver: str,
    requester: str,
    original_quorum: int,
    executor_principal: str | None = None,
) -> ApprovalProfileDecision:
    """Decide whether ``approver`` may approve under the active profile.

    The checks fail closed in a fixed order. A missing profile is the
    multi-operator default. Under the single-operator production profile only
    the named operator may approve, the requester restriction is satisfied by
    that same operator, and the approver must never be the executor identity
    of either the revision or the runtime dispatch.
    """

    effective_quorum = effective_quorum_for(profile, original_quorum)
    kind = ApprovalProfileKind.MULTI_OPERATOR if profile is None else profile.approval_profile
    operator = None if profile is None else profile.operator_principal

    def refuse(reason: ApprovalProfileRefusal) -> ApprovalProfileDecision:
        return ApprovalProfileDecision(
            allowed=False,
            approval_profile=kind,
            original_quorum=original_quorum,
            effective_quorum=effective_quorum,
            refusal=reason,
            operator_principal=operator,
        )

    if not approver.strip():
        return refuse(ApprovalProfileRefusal.BLANK_APPROVER)
    if not requester.strip():
        return refuse(ApprovalProfileRefusal.UNKNOWN_REQUESTER)
    executors = {
        _normalized(value)
        for value in (
            None if profile is None else profile.executor_principal,
            executor_principal,
        )
        if value is not None and value.strip()
    }
    if _normalized(approver) in executors:
        return refuse(ApprovalProfileRefusal.APPROVER_IS_EXECUTOR)
    self_approval = _normalized(approver) == _normalized(requester)
    if profile is None or not profile.is_single_operator:
        if self_approval:
            return refuse(ApprovalProfileRefusal.SELF_APPROVAL)
        return ApprovalProfileDecision(
            allowed=True,
            approval_profile=kind,
            original_quorum=original_quorum,
            effective_quorum=effective_quorum,
        )
    if not profile.names(approver):
        return refuse(ApprovalProfileRefusal.UNNAMED_PRINCIPAL)
    return ApprovalProfileDecision(
        allowed=True,
        approval_profile=kind,
        original_quorum=original_quorum,
        effective_quorum=effective_quorum,
        operator_principal=operator,
        self_review=self_approval,
    )


def approval_profile_from_audit_dict(
    raw: Mapping[str, Any] | None,
) -> ApprovalProfileRevision | None:
    """Reconstruct a validated profile revision from an audit/park payload."""

    if raw is None:
        return None
    try:
        effective_from = datetime.fromisoformat(str(raw["effective_from"]))
        operator = raw.get("operator_principal")
        return ApprovalProfileRevision(
            revision_id=str(raw["revision_id"]),
            approval_profile=ApprovalProfileKind(str(raw["approval_profile"])),
            executor_principal=str(raw["executor_principal"]),
            policy_digest=str(raw["policy_digest"]),
            effective_from=effective_from,
            operator_principal=(str(operator) if operator is not None else None),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("approval profile payload is malformed") from exc


def profile_transition_quorum(
    active: ApprovalProfileRevision | None,
    proposed: ApprovalProfileRevision,
    *,
    governance_quorum: int,
) -> int:
    """Return the approvals needed to activate ``proposed`` under ``active``.

    A change follows the governance rule of the *active* profile. Entering the
    single-operator profile from multi-operator needs the multi-operator
    governance quorum, which is never below two. The single operator can move
    the installation back to multi-operator alone.
    """

    if isinstance(governance_quorum, bool) or governance_quorum < 2:
        raise ValueError("multi-operator governance quorum MUST be an integer >= 2")
    del proposed  # The active profile alone selects the governance rule.
    if active is not None and active.is_single_operator:
        return 1
    return governance_quorum


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
    "apply_operator_policy",
    "effective_quorum_for",
    "evaluate_profile_approval",
    "profile_transition_quorum",
]
