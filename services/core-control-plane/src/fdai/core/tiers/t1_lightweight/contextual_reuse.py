"""Current-evidence gate for immutable operational-case reuse."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from fdai.shared.contracts.models import Event

if TYPE_CHECKING:
    from .tier import LearnedAction

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_CASE_REF = re.compile(
    r"^case-history:([a-z0-9]+(?:[._-][a-z0-9]+)*):([1-9][0-9]*):([0-9a-f]{64})$"
)
_MAX_EVIDENCE_REFS = 64


@dataclass(frozen=True, slots=True)
class OperationalCaseContext:
    """Immutable case and environment facts required for contextual reuse."""

    case_ref: str
    failure_fingerprint: str
    resource_type: str
    action_type: str
    required_topology_role: str
    graph_digest: str
    owner_digest: str
    evidence_cutoff: datetime

    def __post_init__(self) -> None:
        if _CASE_REF.fullmatch(self.case_ref) is None:
            raise ValueError("operational case_ref MUST be an immutable case-history reference")
        for name, value in (
            ("failure_fingerprint", self.failure_fingerprint),
            ("graph_digest", self.graph_digest),
            ("owner_digest", self.owner_digest),
        ):
            if _SHA256.fullmatch(value) is None:
                raise ValueError(f"operational case {name} MUST be lowercase SHA-256")
        for name, value in (
            ("resource_type", self.resource_type),
            ("action_type", self.action_type),
            ("required_topology_role", self.required_topology_role),
        ):
            if _IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"operational case {name} MUST be a canonical identifier")
        if self.evidence_cutoff.tzinfo is None:
            raise ValueError("operational case evidence_cutoff MUST be timezone-aware")

    def to_mapping(self) -> dict[str, object]:
        return {
            "case_ref": self.case_ref,
            "failure_fingerprint": self.failure_fingerprint,
            "resource_type": self.resource_type,
            "action_type": self.action_type,
            "required_topology_role": self.required_topology_role,
            "graph_digest": self.graph_digest,
            "owner_digest": self.owner_digest,
            "evidence_cutoff": self.evidence_cutoff.isoformat(),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> OperationalCaseContext:
        expected = {
            "case_ref",
            "failure_fingerprint",
            "resource_type",
            "action_type",
            "required_topology_role",
            "graph_digest",
            "owner_digest",
            "evidence_cutoff",
        }
        if set(value) != expected:
            raise ValueError("operational case context has unexpected fields")
        cutoff = value.get("evidence_cutoff")
        if not isinstance(cutoff, str):
            raise ValueError("operational case context cutoff MUST be a timestamp")
        return cls(
            case_ref=_required_text(value, "case_ref"),
            failure_fingerprint=_required_text(value, "failure_fingerprint"),
            resource_type=_required_text(value, "resource_type"),
            action_type=_required_text(value, "action_type"),
            required_topology_role=_required_text(value, "required_topology_role"),
            graph_digest=_required_text(value, "graph_digest"),
            owner_digest=_required_text(value, "owner_digest"),
            evidence_cutoff=datetime.fromisoformat(cutoff.replace("Z", "+00:00")),
        )


@dataclass(frozen=True, slots=True)
class CurrentReuseVerification:
    """Fresh observed facts and deterministic safety checks for one reuse."""

    case_ref: str
    observed_at: datetime
    evidence_refs: tuple[str, ...]
    failure_fingerprint: str
    resource_type: str
    topology_role: str
    graph_digest: str
    owner_digest: str
    preconditions_passed: bool
    target_identity_verified: bool
    blast_radius_within_limit: bool
    policy_allowed: bool
    dry_run_passed: bool
    idempotency_available: bool
    rollback_resolved: bool

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("current reuse observed_at MUST be timezone-aware")
        if not 1 <= len(self.evidence_refs) <= _MAX_EVIDENCE_REFS or any(
            _SHA256.fullmatch(reference) is None for reference in self.evidence_refs
        ):
            raise ValueError("current reuse evidence_refs MUST contain bounded SHA-256 values")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("current reuse evidence_refs MUST be unique")
        for name, value in (
            ("resource_type", self.resource_type),
            ("topology_role", self.topology_role),
        ):
            if _IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"current reuse {name} MUST be a canonical identifier")
        for name, value in (
            ("failure_fingerprint", self.failure_fingerprint),
            ("graph_digest", self.graph_digest),
            ("owner_digest", self.owner_digest),
        ):
            if _SHA256.fullmatch(value) is None:
                raise ValueError(f"current reuse {name} MUST be lowercase SHA-256")
        checks = (
            self.preconditions_passed,
            self.target_identity_verified,
            self.blast_radius_within_limit,
            self.policy_allowed,
            self.dry_run_passed,
            self.idempotency_available,
            self.rollback_resolved,
        )
        if any(not isinstance(check, bool) for check in checks):
            raise ValueError("current reuse safety checks MUST be boolean")


class CurrentReuseVerifier(Protocol):
    """Collect current evidence without granting execution authority."""

    async def verify(
        self,
        *,
        event: Event,
        action: LearnedAction,
        context: OperationalCaseContext,
    ) -> CurrentReuseVerification: ...


def contextual_reuse_reasons(
    *,
    event: Event,
    action: LearnedAction,
    context: OperationalCaseContext,
    verification: CurrentReuseVerification,
) -> tuple[str, ...]:
    """Return every deterministic reason that blocks contextual reuse."""
    reasons: list[str] = []
    event_resource_type = _event_resource_type(event)
    if action.action_type != context.action_type:
        reasons.append("operational_case_action_type_changed")
    if verification.case_ref != context.case_ref:
        reasons.append("current_case_ref_conflict")
    if verification.observed_at <= context.evidence_cutoff:
        reasons.append("current_evidence_stale")
    if (
        event_resource_type != context.resource_type
        or verification.resource_type != context.resource_type
    ):
        reasons.append("current_resource_type_changed")
    if verification.failure_fingerprint != context.failure_fingerprint:
        reasons.append("current_failure_fingerprint_changed")
    if verification.topology_role != context.required_topology_role:
        reasons.append("current_topology_role_changed")
    if verification.graph_digest != context.graph_digest:
        reasons.append("current_graph_changed")
    if verification.owner_digest != context.owner_digest:
        reasons.append("current_owner_changed")
    checks = (
        (verification.preconditions_passed, "current_precondition_failed"),
        (verification.target_identity_verified, "current_target_identity_unverified"),
        (verification.blast_radius_within_limit, "current_blast_radius_exceeded"),
        (verification.policy_allowed, "current_policy_denied"),
        (verification.dry_run_passed, "current_dry_run_failed"),
        (verification.idempotency_available, "current_idempotency_conflict"),
        (verification.rollback_resolved, "historical_rollback_unresolved"),
    )
    reasons.extend(reason for passed, reason in checks if not passed)
    return tuple(reasons)


def _event_resource_type(event: Event) -> str:
    payload = event.payload
    resource = payload.get("resource") if isinstance(payload, Mapping) else None
    if not isinstance(resource, Mapping):
        return ""
    resource_type = resource.get("type")
    return resource_type if isinstance(resource_type, str) else ""


def _required_text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"operational case context {key} MUST be non-empty")
    return item


__all__ = [
    "CurrentReuseVerification",
    "CurrentReuseVerifier",
    "OperationalCaseContext",
    "contextual_reuse_reasons",
]
