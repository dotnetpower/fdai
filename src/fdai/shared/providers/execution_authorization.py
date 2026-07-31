"""Injected pre-dispatch execution-authorization evaluation contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable


class ExecutionAuthorizationStatus(StrEnum):
    AUTHORIZED = "authorized"
    GRANT_REQUIRED = "grant_required"
    DELEGATED = "delegated"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"
    POLICY_CONFLICT = "policy_conflict"
    UNCONFIGURED = "unconfigured"


class EffectiveAccessStatus(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    UNKNOWN = "unknown"


class AuthorizationScopeResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ExecutionAuthorizationRequest:
    action_id: str
    action_type_id: str
    target_resource_ref: str
    correlation_id: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.action_id,
                self.action_type_id,
                self.target_resource_ref,
                self.correlation_id,
                self.idempotency_key,
            )
        ):
            raise ValueError("execution authorization request fields MUST be non-empty")


@dataclass(frozen=True, slots=True)
class ExecutionAuthorizationContext:
    organization: str
    account: str
    resource_group: str
    resource_id: str
    resource_type: str
    inventory_generation: str
    evaluated_at: datetime
    requester_ref: str
    tags: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.organization,
                self.account,
                self.resource_group,
                self.resource_id,
                self.resource_type,
                self.inventory_generation,
                self.requester_ref,
            )
        ):
            raise ValueError("execution authorization context fields MUST be non-empty")
        if self.evaluated_at.tzinfo is None:
            raise ValueError("execution authorization context time MUST be timezone-aware")


@runtime_checkable
class ExecutionAuthorizationContextProvider(Protocol):
    async def resolve_context(
        self,
        request: ExecutionAuthorizationRequest,
    ) -> ExecutionAuthorizationContext: ...


@dataclass(frozen=True, slots=True)
class AuthorizationScopeResolution:
    status: AuthorizationScopeResolutionStatus
    scope_refs: tuple[str, ...]
    evidence_digest: str
    reason_code: str

    def __post_init__(self) -> None:
        if not self.evidence_digest.strip() or not self.reason_code.strip():
            raise ValueError("authorization scope resolution evidence MUST be non-empty")
        if self.status is AuthorizationScopeResolutionStatus.RESOLVED and not self.scope_refs:
            raise ValueError("resolved authorization scope MUST contain at least one scope")
        if self.status is AuthorizationScopeResolutionStatus.UNKNOWN and self.scope_refs:
            raise ValueError("unknown authorization scope MUST NOT contain scope references")


@runtime_checkable
class ExecutionAuthorizationScopeResolver(Protocol):
    async def resolve_scopes(
        self,
        *,
        request: ExecutionAuthorizationRequest,
        context: ExecutionAuthorizationContext,
        scope_expressions: tuple[str, ...],
    ) -> AuthorizationScopeResolution: ...


@dataclass(frozen=True, slots=True)
class ExecutionAuthorizationResult:
    status: ExecutionAuthorizationStatus
    decision_digest: str
    evaluator_ref: str
    reason_codes: tuple[str, ...]
    audit_context: Mapping[str, object] = field(default_factory=dict)
    grant_proposals: tuple[ExecutionAccessGrantProposal, ...] = ()

    def __post_init__(self) -> None:
        if (
            not self.decision_digest.strip()
            or not self.evaluator_ref.strip()
            or not self.reason_codes
        ):
            raise ValueError("execution authorization result evidence MUST be non-empty")
        if self.status is ExecutionAuthorizationStatus.GRANT_REQUIRED and not self.grant_proposals:
            raise ValueError("grant_required authorization MUST carry grant proposals")
        if self.status is not ExecutionAuthorizationStatus.GRANT_REQUIRED and self.grant_proposals:
            raise ValueError("only grant_required authorization may carry grant proposals")
        if any(
            proposal.authorization_decision_digest != self.decision_digest
            for proposal in self.grant_proposals
        ):
            raise ValueError("grant proposals MUST bind the authorization decision digest")
        proposal_keys = tuple(
            (proposal.requirement_id, proposal.scope_ref) for proposal in self.grant_proposals
        )
        if proposal_keys != tuple(sorted(set(proposal_keys))):
            raise ValueError("grant proposals MUST be unique and canonically ordered")
        normalized = _safe_audit_context(self.audit_context)
        object.__setattr__(self, "audit_context", MappingProxyType(normalized))

    @property
    def can_enter_risk_gate(self) -> bool:
        return self.status is ExecutionAuthorizationStatus.AUTHORIZED


@runtime_checkable
class ExecutionAuthorizationEvaluator(Protocol):
    async def evaluate(
        self,
        request: ExecutionAuthorizationRequest,
    ) -> ExecutionAuthorizationResult: ...


@dataclass(frozen=True, slots=True)
class ExecutionAccessGrantProposal:
    idempotency_key: str
    original_action_id: str
    authorization_decision_digest: str
    requirement_id: str
    capability_id: str
    execution_profile: str
    executor_identity_ref: str
    scope_ref: str
    grant_mode: str
    mapping_digest: str
    plan_digest: str
    requester_ref: str
    requested_at: datetime
    expires_at: datetime
    quorum: int
    approver_roles: frozenset[str]

    def __post_init__(self) -> None:
        required = (
            self.idempotency_key,
            self.original_action_id,
            self.authorization_decision_digest,
            self.requirement_id,
            self.capability_id,
            self.execution_profile,
            self.executor_identity_ref,
            self.scope_ref,
            self.grant_mode,
            self.mapping_digest,
            self.plan_digest,
            self.requester_ref,
        )
        if any(not value.strip() for value in required):
            raise ValueError("execution access-grant proposal fields MUST be non-empty")
        if self.requested_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("execution access-grant proposal timestamps MUST be timezone-aware")
        if self.expires_at <= self.requested_at or self.quorum < 1 or not self.approver_roles:
            raise ValueError("execution access-grant proposal bounds MUST be valid")


@runtime_checkable
class ExecutionAccessGrantSink(Protocol):
    async def submit_grant(self, proposal: ExecutionAccessGrantProposal) -> str: ...


@dataclass(frozen=True, slots=True)
class ExecutionAccessGrantPlanRequest:
    authorization_decision_digest: str
    original_request: ExecutionAuthorizationRequest
    requirement_id: str
    capability_id: str
    execution_profile: str
    executor_identity_ref: str
    scope_ref: str
    mapping_digest: str
    allowed_grant_modes: frozenset[str]
    max_duration_seconds: int
    quorum: int
    approver_roles: frozenset[str]
    requester_ref: str
    requested_at: datetime

    def __post_init__(self) -> None:
        required = (
            self.authorization_decision_digest,
            self.requirement_id,
            self.capability_id,
            self.execution_profile,
            self.executor_identity_ref,
            self.scope_ref,
            self.mapping_digest,
            self.requester_ref,
        )
        if any(not value.strip() for value in required):
            raise ValueError("execution access-grant plan fields MUST be non-empty")
        if not self.scope_ref.startswith("scope://"):
            raise ValueError("execution access-grant plan scope MUST use a scope:// reference")
        if (
            not self.allowed_grant_modes
            or self.max_duration_seconds < 1
            or self.quorum < 1
            or not self.approver_roles
        ):
            raise ValueError("execution access-grant plan bounds MUST be valid")
        if self.requested_at.tzinfo is None:
            raise ValueError("execution access-grant plan time MUST be timezone-aware")


@runtime_checkable
class ExecutionAccessGrantPlanner(Protocol):
    async def plan_grant(
        self,
        request: ExecutionAccessGrantPlanRequest,
    ) -> ExecutionAccessGrantProposal: ...


@dataclass(frozen=True, slots=True)
class ExecutionIdentityBinding:
    execution_profile: str
    identity_ref: str
    binding_digest: str


@runtime_checkable
class ExecutionIdentityResolver(Protocol):
    async def resolve(
        self,
        *,
        execution_profile: str,
        target_resource_ref: str,
    ) -> ExecutionIdentityBinding: ...


@dataclass(frozen=True, slots=True)
class ProviderPermissionMapping:
    capability_id: str
    provider: str
    operations: tuple[str, ...]
    audience_ref: str
    authorization_plane: str
    mapping_digest: str

    def __post_init__(self) -> None:
        if not self.operations:
            raise ValueError("provider permission mapping operations MUST be non-empty")


@runtime_checkable
class ProviderPermissionMapper(Protocol):
    def resolve(self, capability_id: str) -> ProviderPermissionMapping: ...


@dataclass(frozen=True, slots=True)
class EffectiveAuthorizationProbeRequest:
    identity_ref: str
    capability_id: str
    operations: tuple[str, ...]
    audience_ref: str
    scope_ref: str
    mapping_digest: str


@dataclass(frozen=True, slots=True)
class EffectiveAuthorizationProbeResult:
    status: EffectiveAccessStatus
    evidence_digest: str
    observed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("effective authorization evidence MUST be timezone-aware")
        if self.expires_at <= self.observed_at:
            raise ValueError("effective authorization evidence expiry MUST follow observation")


@runtime_checkable
class EffectiveAuthorizationProbe(Protocol):
    async def probe(
        self,
        request: EffectiveAuthorizationProbeRequest,
    ) -> EffectiveAuthorizationProbeResult: ...


def _safe_audit_context(value: Mapping[str, object]) -> dict[str, object]:
    sensitive = ("credential", "password", "secret", "token", "endpoint", "url")
    if any(any(fragment in key.casefold() for fragment in sensitive) for key in value):
        raise ValueError("execution authorization audit context contains a sensitive key")
    try:
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=True, sort_keys=True)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError("execution authorization audit context MUST be canonical JSON") from exc
    if not isinstance(decoded, dict):  # pragma: no cover - Mapping encodes as an object
        raise ValueError("execution authorization audit context MUST be an object")
    return {str(key): item for key, item in decoded.items()}


__all__ = [
    "AuthorizationScopeResolution",
    "AuthorizationScopeResolutionStatus",
    "ExecutionAuthorizationEvaluator",
    "ExecutionAuthorizationRequest",
    "ExecutionAuthorizationResult",
    "ExecutionAuthorizationStatus",
    "EffectiveAccessStatus",
    "ExecutionAuthorizationContext",
    "ExecutionAuthorizationContextProvider",
    "ExecutionAuthorizationScopeResolver",
    "ExecutionAccessGrantProposal",
    "ExecutionAccessGrantPlanRequest",
    "ExecutionAccessGrantPlanner",
    "ExecutionAccessGrantSink",
    "EffectiveAuthorizationProbe",
    "EffectiveAuthorizationProbeRequest",
    "EffectiveAuthorizationProbeResult",
    "ExecutionIdentityBinding",
    "ExecutionIdentityResolver",
    "ProviderPermissionMapper",
    "ProviderPermissionMapping",
]
