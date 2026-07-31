"""Provider-neutral execution-authorization decision contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from fdai.rule_catalog.schema.execution_authorization import (
    AuthorizationConstraints,
    AuthorizationEnforcement,
    AuthorizationPolicyAssignment,
    AuthorizationPosture,
    AuthorizationScopeLevel,
    GrantMode,
)
from fdai.shared.providers.execution_authorization import (
    ExecutionAuthorizationStatus as AuthorizationStatus,
)


class AccessObservationStatus(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AuthorizationRequirement:
    requirement_id: str
    capability_id: str
    action_type_ids: frozenset[str]
    resource_types: frozenset[str]
    scope_refs: tuple[str, ...]
    execution_profile: str
    mapping_digest: str

    def __post_init__(self) -> None:
        values = (
            self.requirement_id,
            self.capability_id,
            self.execution_profile,
            self.mapping_digest,
        )
        if any(not value.strip() for value in values):
            raise ValueError("authorization requirement identifiers MUST be non-empty")
        if not self.action_type_ids or not self.resource_types or not self.scope_refs:
            raise ValueError("authorization requirement selectors and scopes MUST be non-empty")
        if any(not scope.startswith("scope://") for scope in self.scope_refs):
            raise ValueError("authorization requirement scopes MUST use scope:// references")

    def applies_to(self, *, action_type_id: str, resource_type: str) -> bool:
        return action_type_id in self.action_type_ids and resource_type in self.resource_types


@dataclass(frozen=True, slots=True)
class AuthorizationObservation:
    observation_id: str
    identity_ref: str
    capability_id: str
    scope_ref: str
    mapping_digest: str
    status: AccessObservationStatus
    observed_at: datetime
    expires_at: datetime
    evidence_digest: str

    def __post_init__(self) -> None:
        values = (
            self.observation_id,
            self.identity_ref,
            self.capability_id,
            self.scope_ref,
            self.mapping_digest,
            self.evidence_digest,
        )
        if any(not value.strip() for value in values):
            raise ValueError("authorization observation identifiers MUST be non-empty")
        if not self.scope_ref.startswith("scope://"):
            raise ValueError("authorization observation scope MUST use a scope:// reference")
        if self.observed_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("authorization observation timestamps MUST be timezone-aware")
        if self.expires_at <= self.observed_at:
            raise ValueError("authorization observation expiry MUST follow observation time")


@dataclass(frozen=True, slots=True)
class ResolvedAuthorizationConstraints:
    allowed_grant_modes: frozenset[GrantMode]
    max_scope: AuthorizationScopeLevel
    max_duration_seconds: int
    quorum: int
    approver_roles: frozenset[str]
    required_evidence: frozenset[str]
    require_effective_probe: bool
    exemptible: bool


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    status: AuthorizationStatus
    action_type_id: str
    capability_id: str
    requirement_id: str
    execution_profile: str
    identity_ref: str
    scope_refs: tuple[str, ...]
    assignment_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    observation_evidence_digests: tuple[str, ...]
    reasons: tuple[str, ...]
    policy_bundle_digest: str
    inventory_generation: str
    algorithm_version: str
    decision_digest: str
    constraints: ResolvedAuthorizationConstraints | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    @property
    def can_enter_risk_gate(self) -> bool:
        return self.status is AuthorizationStatus.AUTHORIZED

    def as_audit_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "action_type_id": self.action_type_id,
            "capability_id": self.capability_id,
            "requirement_id": self.requirement_id,
            "execution_profile": self.execution_profile,
            "identity_ref": self.identity_ref,
            "scope_refs": list(self.scope_refs),
            "assignment_ids": list(self.assignment_ids),
            "observation_ids": list(self.observation_ids),
            "observation_evidence_digests": list(self.observation_evidence_digests),
            "reasons": list(self.reasons),
            "policy_bundle_digest": self.policy_bundle_digest,
            "inventory_generation": self.inventory_generation,
            "algorithm_version": self.algorithm_version,
            "decision_digest": self.decision_digest,
        }


__all__ = [
    "AccessObservationStatus",
    "AuthorizationConstraints",
    "AuthorizationDecision",
    "AuthorizationEnforcement",
    "AuthorizationObservation",
    "AuthorizationPolicyAssignment",
    "AuthorizationPosture",
    "AuthorizationRequirement",
    "AuthorizationScopeLevel",
    "AuthorizationStatus",
    "GrantMode",
    "ResolvedAuthorizationConstraints",
]
