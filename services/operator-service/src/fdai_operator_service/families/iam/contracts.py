"""Injected records and Protocols for the non-privileged IAM route family.

Mutation ports persist typed requests or outbox records. They never expose an
identity-provider client, executor, or managed-resource mutation method.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, TypeAlias, runtime_checkable

from fdai_service_contracts import JsonObject, OperatorRole
from starlette.requests import Request

JsonMapping: TypeAlias = Mapping[str, Any]  # noqa: UP040


@dataclass(frozen=True, slots=True)
class IamPrincipal:
    """Verified human identity with server-derived roles and optional display name."""

    oid: str
    roles: frozenset[OperatorRole]
    username: str | None = None

    def __post_init__(self) -> None:
        if not self.oid.strip():
            raise ValueError("IAM principal oid MUST be non-empty")


AuthorizePrincipal: TypeAlias = Callable[[Request], Awaitable[IamPrincipal]]  # noqa: UP040


@dataclass(frozen=True, slots=True)
class AccessGrantRecord:
    """Browser-safe execution access grant projection with no identity secret fields."""

    request_id: str
    correlation_id: str
    capability_id: str
    scope_ref: str
    grant_mode: str
    requested_at: datetime
    expires_at: datetime
    quorum: int
    status: str
    revision: int

    def to_dict(self) -> JsonObject:
        """Return the exact bounded browser projection."""
        return {
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "capability_id": self.capability_id,
            "scope_ref": self.scope_ref,
            "grant_mode": self.grant_mode,
            "requested_at": self.requested_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "quorum": self.quorum,
            "status": self.status,
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class AccessGrantSnapshotQuery:
    """Principal-scoped request for a durable SSE snapshot after a replay cursor."""

    reviewer_ref: str
    reviewer_roles: frozenset[str]
    after_sequence: int | None
    limit: int = 50


@dataclass(frozen=True, slots=True)
class AccessGrantSnapshot:
    """One replay-addressable access-grant snapshot."""

    sequence: int
    generated_at: datetime
    requests: tuple[AccessGrantRecord, ...]


@dataclass(frozen=True, slots=True)
class AccessGrantDecisionCommand:
    """Revision-fenced review request persisted by the injected grant outbox."""

    request_id: str
    reviewer_ref: str
    reviewer_roles: frozenset[str]
    decision: str
    reason: str
    expected_revision: int
    decided_at: datetime


@dataclass(frozen=True, slots=True)
class AccessGrantDecisionResult:
    """Durable review result that does not claim provider permission application."""

    request_id: str
    status: str
    revision: int
    approved_count: int
    quorum: int
    reviewed_at: datetime | None


class AccessGrantOutbox(Protocol):
    """Read pending grants and persist review commands without applying access."""

    async def snapshot(self, query: AccessGrantSnapshotQuery) -> AccessGrantSnapshot: ...

    async def decide(self, command: AccessGrantDecisionCommand) -> AccessGrantDecisionResult: ...


@dataclass(frozen=True, slots=True)
class DirectoryIdentity:
    """Bounded identity-provider projection used for exact-subject validation."""

    provider: str
    subject_id: str
    username: str
    display_name: str | None
    active: bool
    user_type: str = "member"
    principal_type: str = "person"
    roles: tuple[str, ...] = ()

    def to_dict(self) -> JsonObject:
        """Return a browser-safe directory record."""
        return {
            "provider": self.provider,
            "subject_id": self.subject_id,
            "username": self.username,
            "display_name": self.display_name,
            "active": self.active,
            "user_type": self.user_type,
            "principal_type": self.principal_type,
            "roles": list(self.roles),
        }


@dataclass(frozen=True, slots=True)
class DirectoryStatus:
    """Browser-safe availability and freshness metadata for the identity source."""

    source: str
    availability: str
    observed_at: datetime | None = None
    detail: str | None = None

    def to_dict(self) -> JsonObject:
        """Return metadata without exposing provider credentials or tenant values."""
        return {
            "source": self.source,
            "availability": self.availability,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "detail": self.detail,
        }


class HumanIdentityDirectory(Protocol):
    """Read human identities without exposing membership mutation operations."""

    async def search(self, query: str, *, limit: int) -> Sequence[DirectoryIdentity]: ...

    async def list_role_roster(
        self, role_group_ids: Mapping[str, str], *, limit: int
    ) -> Sequence[DirectoryIdentity]: ...

    async def get_by_subject_id(self, subject_id: str) -> DirectoryIdentity | None: ...


@runtime_checkable
class HumanIdentityDirectoryStatus(Protocol):
    """Optional status surface implemented by directories with freshness evidence."""

    async def directory_status(self) -> DirectoryStatus: ...


@runtime_checkable
class StewardshipIdentityDirectory(Protocol):
    """Resolve exact user or group subjects for the read-only ownership projection."""

    async def get_steward_subject_by_id(
        self,
        subject_id: str,
        *,
        kind: str,
    ) -> DirectoryIdentity | None: ...


@dataclass(frozen=True, slots=True)
class AccessRequestQuery:
    """Bounded principal-scoped access request page query."""

    principal: IamPrincipal
    limit: int
    offset: int = 0


@dataclass(frozen=True, slots=True)
class AccessRequestCommand:
    """Typed human access request persisted for independent review and audit."""

    principal: IamPrincipal
    idempotency_key: str
    identity_provider: str
    target_subject_id: str
    target_username: str
    operation: str
    role: OperatorRole
    justification: str
    self_service: bool = False


@dataclass(frozen=True, slots=True)
class AccessReviewCommand:
    """Typed access review persisted without changing provider membership."""

    principal: IamPrincipal
    request_id: str
    decision: str
    justification: str


class HumanAccessRequestOutbox(Protocol):
    """Persist and project governed access requests without applying membership."""

    async def list_request_page(
        self, query: AccessRequestQuery
    ) -> tuple[Sequence[JsonMapping], int]: ...

    async def submit(self, command: AccessRequestCommand) -> JsonMapping: ...

    async def review(self, command: AccessReviewCommand) -> JsonMapping: ...


@dataclass(frozen=True, slots=True)
class AssignmentCaseQuery:
    """Owner-scoped assignment case page query."""

    principal: IamPrincipal
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class AssignmentCreateCommand:
    """Typed assignment intent persisted before any ownership or IAM effect."""

    principal: IamPrincipal
    idempotency_key: str
    subject_provider: str
    subject_id: str
    requested_role: OperatorRole
    duty_bindings: tuple[JsonMapping, ...]
    goal_refs: tuple[str, ...]
    justification: str


@dataclass(frozen=True, slots=True)
class AssignmentTransitionCommand:
    """Revision-fenced assignment lifecycle transition request."""

    principal: IamPrincipal
    case_id: str
    expected_revision: int
    decision: str | None = None


class AssignmentRequestOutbox(Protocol):
    """Persist assignment cases and requests; never apply IAM or ownership effects."""

    async def list_case_page(
        self, query: AssignmentCaseQuery
    ) -> tuple[Sequence[JsonMapping], int]: ...

    async def get_case(self, case_id: str) -> JsonMapping: ...

    async def create_case(self, command: AssignmentCreateCommand) -> JsonMapping: ...

    async def submit_for_review(self, command: AssignmentTransitionCommand) -> JsonMapping: ...

    async def review(self, command: AssignmentTransitionCommand) -> JsonMapping: ...

    async def assignment_projection(self, query: AssignmentCaseQuery) -> JsonMapping: ...


@dataclass(frozen=True, slots=True)
class HandoverGoalCommand:
    """Revision-fenced handover goal command persisted by the goal outbox."""

    principal: IamPrincipal
    goal_id: str
    operation: str
    expected_revision: int
    reason_ref: str | None = None
    evidence_ref: str | None = None
    digest: str | None = None
    kind: str | None = None


class HandoverGoalOutbox(Protocol):
    """Project invitations and persist goal commands without provider effects."""

    async def invitation_for_session(
        self, *, subject_ref: str, session_id: str
    ) -> JsonMapping | None: ...

    async def get_goal(self, goal_id: str) -> JsonMapping: ...

    async def submit(self, command: HandoverGoalCommand) -> JsonMapping: ...


@dataclass(frozen=True, slots=True)
class ModelPreferenceCommand:
    """Principal-scoped model preference write with an exact expected revision."""

    principal_id: str
    preferred_narrator_model: str
    expected_revision: int


@dataclass(frozen=True, slots=True)
class WebSearchSettingsCommand:
    """Owner-scoped web-search policy request persisted with audit metadata."""

    actor_id: str
    enabled: bool
    allowed_domains: tuple[str, ...]
    expected_revision: int


@dataclass(frozen=True, slots=True)
class ModelBindingDraftCommand:
    """Owner-scoped environment binding draft with revision and idempotency fences."""

    actor_id: str
    policy: JsonMapping
    policy_digest: str
    expected_revision: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ModelBindingRequestCommand:
    """Request protected assessment or planning for one exact stored policy."""

    actor_id: str
    environment: str
    policy_revision: int
    policy_digest: str
    idempotency_key: str


class ModelSettingsOutbox(Protocol):
    """Project model settings and persist policy requests without provisioning models."""

    async def projection(
        self,
        principal_id: str,
        *,
        can_manage_web_search: bool = False,
        can_manage_model_bindings: bool = False,
        refresh_model_catalog: bool = False,
    ) -> JsonMapping: ...

    async def set_preference(self, command: ModelPreferenceCommand) -> None: ...

    async def set_web_search_settings(self, command: WebSearchSettingsCommand) -> None: ...

    async def save_binding_policy(self, command: ModelBindingDraftCommand) -> JsonMapping: ...

    async def request_binding_assessment(
        self, command: ModelBindingRequestCommand
    ) -> JsonMapping: ...

    async def request_binding_plan(self, command: ModelBindingRequestCommand) -> JsonMapping: ...


@dataclass(frozen=True, slots=True)
class RuntimeSettingsCommand:
    """Owner-scoped allowlisted runtime settings request."""

    actor_id: str
    changes: JsonMapping
    expected_revision: int


class RuntimeSettingsOutbox(Protocol):
    """Project runtime settings and persist revisioned overrides only."""

    async def projection(self, *, can_manage: bool) -> JsonMapping: ...

    async def update(self, command: RuntimeSettingsCommand) -> None: ...


@dataclass(frozen=True, slots=True)
class TeamsWorkflowTestCommand:
    """One Owner-scoped synthetic notification test with a transient URL."""

    actor_id: str
    request_id: str
    webhook_url: str


@dataclass(frozen=True, slots=True)
class TeamsWorkflowTestResult:
    """Secret-free result returned after one bounded provider request."""

    request_id: str
    saved: bool
    binding_version: str
    saved_at: datetime
    accepted: bool
    provider_status: int
    workflow_run_id: str | None
    tested_at: datetime


class TeamsWorkflowTester(Protocol):
    """Persist one endpoint, then send and audit one synthetic notification."""

    async def save_and_test(self, command: TeamsWorkflowTestCommand) -> TeamsWorkflowTestResult: ...

    async def describe_binding(
        self,
        *,
        actor_id: str,
    ) -> JsonMapping | None:
        """Return secret-free saved-binding metadata; never the endpoint value."""
        ...


@dataclass(frozen=True, slots=True)
class SlackWebhookTestCommand:
    """One Owner-scoped synthetic Slack notification test with a transient URL."""

    actor_id: str
    request_id: str
    webhook_url: str


@dataclass(frozen=True, slots=True)
class SlackWebhookTestResult:
    """Secret-free result returned after one bounded Slack request."""

    request_id: str
    accepted: bool
    provider_status: int
    tested_at: datetime


class SlackWebhookTester(Protocol):
    """Send and durably audit one synthetic Slack incoming-webhook notification."""

    async def test(self, command: SlackWebhookTestCommand) -> SlackWebhookTestResult: ...


@dataclass(frozen=True, slots=True)
class KillSwitchCommand:
    """Idempotent emergency-stop state request persisted with atomic audit."""

    engaged: bool
    actor_oid: str
    reason: str
    request_id: str


class KillSwitchOutbox(Protocol):
    """Persist an emergency-stop request without executing a provider change."""

    async def submit(self, command: KillSwitchCommand) -> JsonMapping: ...


@dataclass(frozen=True, slots=True)
class BreakGlassActivationCommand:
    """Time-boxed emergency activation request recorded for audit only."""

    actor_oid: str
    incident_id: str
    reason: str
    activated_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class BreakGlassActivationRecord:
    """Durable activation record.

    The projection carries no role set, token, grant, or executor identity, so
    an activation can never be mistaken for an approval or an execution right.
    """

    activation_id: str
    actor_oid: str
    incident_id: str
    activated_at: datetime
    expires_at: datetime

    def to_dict(self) -> JsonObject:
        """Return the exact bounded activation projection."""
        return {
            "activation_id": self.activation_id,
            "actor_oid": self.actor_oid,
            "incident_id": self.incident_id,
            "activated_at": self.activated_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "grants_hil_approval": False,
            "grants_executor_identity": False,
        }


class BreakGlassActivationOutbox(Protocol):
    """Persist the activation audit record without elevating any principal."""

    async def activate(
        self, command: BreakGlassActivationCommand
    ) -> BreakGlassActivationRecord: ...


@dataclass(frozen=True, slots=True)
class ConfigurationReviewCommand:
    """Typed evidence campaign request with an idempotency identity."""

    principal_id: str
    run_id: str
    requested_at: datetime


class ConfigurationReviewOutbox(Protocol):
    """Persist evidence campaign commands without invoking managed-resource mutation."""

    async def run(self, command: ConfigurationReviewCommand) -> JsonMapping: ...

    async def resume(self, *, principal_id: str) -> JsonMapping: ...


class HilApprovalDecision(StrEnum):
    """Human decisions accepted by the signed HIL callback."""

    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class HilPendingItem:
    """Minimum authoritative pending record needed for callback authorization."""

    approval_id: str
    idempotency_key: str
    submitter_oid: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HilDecisionReceipt:
    """Durable decision receipt whose delivery can be replayed through the outbox."""

    approval_id: str
    idempotency_key: str
    decision: HilApprovalDecision
    approver_oid: str
    decided_at: datetime
    receipt_ref: str
    justification: str = ""
    already_recorded: bool = False
    delivered: bool = False


@dataclass(frozen=True, slots=True)
class HilDecisionCommand:
    """Signed callback decision persisted by the approval registry."""

    idempotency_key: str
    decision: HilApprovalDecision
    approver_oid: str
    justification: str
    decided_at: datetime


@dataclass(frozen=True, slots=True)
class HilDecisionOutboxRequest:
    """Typed durable delivery request for an already-recorded HIL decision."""

    receipt: HilDecisionReceipt


class HilDecisionRegistry(Protocol):
    """Read pending items and persist idempotent decisions with delivery state."""

    async def get_pending_by_approval_id(self, approval_id: str) -> HilPendingItem | None: ...

    async def get_decision_by_approval_id(self, approval_id: str) -> HilDecisionReceipt | None: ...

    async def record_decision(self, command: HilDecisionCommand) -> HilDecisionReceipt: ...

    async def mark_delivered(self, receipt: HilDecisionReceipt) -> HilDecisionReceipt: ...


class HilDecisionOutbox(Protocol):
    """Durably enqueue a recorded decision for typed transport delivery."""

    async def enqueue(self, request: HilDecisionOutboxRequest) -> None: ...


__all__ = [name for name in globals() if not name.startswith("_")]
