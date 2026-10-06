"""Authority-neutral approval profile contract shared by Core and Operator."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

_DIGEST_PREFIX = "sha256:"
_DIGEST_LENGTH = len(_DIGEST_PREFIX) + 64
_REVISION_DIGEST_FIELDS = (
    "revision_id",
    "approval_profile",
    "executor_principal",
    "effective_from",
    "operator_principal",
)


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


def approval_profile_effective_from(value: object) -> datetime:
    """Return the canonical effective time or reject non-canonical input."""

    if not isinstance(value, str):
        raise ValueError("approval profile effective_from MUST be a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("approval profile effective_from MUST be valid ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("approval profile effective_from MUST be timezone-aware")
    if value != parsed.isoformat():
        raise ValueError("approval profile effective_from MUST be canonical")
    return parsed


def approval_profile_policy_digest(revision: Mapping[str, Any]) -> str:
    """Return the content-addressed digest for an approval profile revision."""

    canonical = {field: revision.get(field) for field in _REVISION_DIGEST_FIELDS}
    encoded = json.dumps(
        canonical,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _DIGEST_PREFIX + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ApprovalProfileRevision:
    """One immutable approval policy revision that selects a profile."""

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
    """Decide whether ``approver`` may approve under the active profile."""

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


def profile_transition_quorum(
    active: ApprovalProfileRevision | None,
    proposed: ApprovalProfileRevision,
    *,
    governance_quorum: int,
) -> int:
    """Return the approvals needed to activate ``proposed`` under ``active``."""

    if isinstance(governance_quorum, bool) or governance_quorum < 2:
        raise ValueError("multi-operator governance quorum MUST be an integer >= 2")
    del proposed
    if active is not None and active.is_single_operator:
        return 1
    return governance_quorum


_AUDIT_REQUIRED_FIELDS = (
    "revision_id",
    "approval_profile",
    "executor_principal",
    "policy_digest",
    "effective_from",
)


def approval_profile_from_audit_dict(
    raw: Mapping[str, Any] | None,
) -> ApprovalProfileRevision | None:
    """Reconstruct a validated profile revision from an audit/park payload."""

    if raw is None:
        return None
    if any(field not in raw for field in _AUDIT_REQUIRED_FIELDS):
        raise ValueError("approval profile payload is malformed")
    if raw.get("policy_digest") != approval_profile_policy_digest(raw):
        raise ValueError("approval profile payload digest is mismatched")
    effective_from = approval_profile_effective_from(raw["effective_from"])
    try:
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


__all__ = [
    "ApprovalProfileDecision",
    "ApprovalProfileKind",
    "ApprovalProfileRefusal",
    "ApprovalProfileRevision",
    "approval_profile_effective_from",
    "approval_profile_from_audit_dict",
    "approval_profile_policy_digest",
    "effective_quorum_for",
    "evaluate_profile_approval",
    "profile_transition_quorum",
]
