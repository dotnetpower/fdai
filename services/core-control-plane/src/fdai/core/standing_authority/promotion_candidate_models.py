"""Immutable record models for the A3-E inert promotion-candidate lifecycle.

Defines constants, enums, frozen dataclasses, and the ``PromotionCandidateStore``
persistence protocol. No execution or promotion authority is granted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from fdai.core.standing_authority.lifecycle import LifecycleFence
from fdai.core.standing_authority.lifecycle_codec import (
    AuthorizationLifecycleError,
    aware_utc,
    content_digest,
    instant,
    require_aware,
    require_digest,
    require_text,
)
from fdai.core.standing_authority.provider_eligibility import (
    derive_ineligible_provider_action_types,
)

LEASE_CONTRACT_VERSION: str = "a3e-lease-v1"
CANDIDATE_QUORUM: int = 2


class CandidateStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class CandidateTransitionKind(StrEnum):
    CREATE = "create"
    REVIEW = "review"
    DENY = "deny"


class DenialReason(StrEnum):
    REVOKED = "revoked"
    EXPIRED = "expired"
    STALE_FENCE = "stale_fence"
    LEASE_INCOMPATIBLE = "lease_incompatible"
    PROVIDER_INELIGIBLE = "provider_ineligible"
    MISSING_EVIDENCE = "missing_evidence"
    SELF_REVIEW = "self_review"
    DUPLICATE_REVIEW = "duplicate_review"
    CONFLICTING_REVIEW = "conflicting_review"
    UNAUTHORIZED_REVIEWER = "unauthorized_reviewer"
    MISSING_QUORUM = "missing_quorum"
    REJECTION = "rejection"
    REVOCATION_REQUEST = "revocation_request"


def _require_human(name: str, principal: str) -> None:
    if principal.startswith("agent:") or principal.startswith("identity:thor"):
        raise AuthorizationLifecycleError(f"{name} MUST be human, not agent/executor")
    if not principal.startswith("human:"):
        raise AuthorizationLifecycleError(f"{name} MUST start with 'human:'")


def _require_canonical_distinct(name: str, values: tuple[str, ...]) -> None:
    if len(values) != len(set(values)):
        raise AuthorizationLifecycleError(f"{name} MUST contain distinct values")
    if values != tuple(sorted(values)):
        raise AuthorizationLifecycleError(f"{name} MUST use canonical sorted order")


@dataclass(frozen=True, slots=True)
class PromotionCandidateRecord:
    """Creation record binding revision, fence, lease version, ActionTypes, and reviewers."""

    candidate_id: str
    family_id: str
    revision_id: str
    fence: LifecycleFence
    lease_contract_version: str
    eligible_action_types: tuple[str, ...]
    ineligible_provider_action_types: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    source_revision_id: str
    creator_principal: str
    authentication_evidence_digest: str
    created_at: datetime
    required_reviewer_principals: tuple[str, ...]
    quorum_required: int
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    def __post_init__(self) -> None:
        require_text("family_id", self.family_id)
        require_digest("revision_id", self.revision_id)
        if self.fence.revision_id != self.revision_id or self.fence.family_id != self.family_id:
            raise AuthorizationLifecycleError("fence MUST match revision_id and family_id")
        if self.lease_contract_version != LEASE_CONTRACT_VERSION:
            raise AuthorizationLifecycleError(
                f"lease_contract_version MUST be {LEASE_CONTRACT_VERSION!r}"
            )
        if not self.eligible_action_types:
            raise AuthorizationLifecycleError("eligible_action_types MUST be non-empty")
        for at in (*self.eligible_action_types, *self.ineligible_provider_action_types):
            require_text("action_type", at)
        if not self.evidence_requirements:
            raise AuthorizationLifecycleError("evidence_requirements MUST be non-empty")
        for er in self.evidence_requirements:
            require_text("evidence_requirement", er)
        _require_canonical_distinct("eligible_action_types", self.eligible_action_types)
        _require_canonical_distinct(
            "ineligible_provider_action_types",
            self.ineligible_provider_action_types,
        )
        _require_canonical_distinct("evidence_requirements", self.evidence_requirements)
        # Provider-commit-fence capability is derived, never declared. This closes the
        # direct-constructor path as well as the builder, so no caller can assert that
        # an ActionType is A3-E eligible when its adapter cannot validate the lease and
        # fencing generation atomically at provider commit.
        if self.ineligible_provider_action_types != derive_ineligible_provider_action_types(
            self.eligible_action_types
        ):
            raise AuthorizationLifecycleError(
                "ineligible_provider_action_types MUST equal the derived "
                "provider-commit-fence partition of eligible_action_types"
            )
        require_text("source_revision_id", self.source_revision_id)
        _require_human("creator_principal", self.creator_principal)
        require_digest("authentication_evidence_digest", self.authentication_evidence_digest)
        require_aware("created_at", self.created_at)
        if self.quorum_required < CANDIDATE_QUORUM:
            raise AuthorizationLifecycleError(f"quorum_required MUST be >= {CANDIDATE_QUORUM}")
        if not self.required_reviewer_principals or (
            len(set(self.required_reviewer_principals)) < self.quorum_required
        ):
            raise AuthorizationLifecycleError("insufficient distinct reviewers for quorum")
        for rp in self.required_reviewer_principals:
            _require_human("reviewer_principal", rp)
        _require_canonical_distinct(
            "required_reviewer_principals",
            self.required_reviewer_principals,
        )
        if self.execution_authority is not False or self.promotion_authority is not False:
            raise AuthorizationLifecycleError("authority flags MUST be False")
        expected = content_digest(
            {
                "family_id": self.family_id,
                "revision_id": self.revision_id,
                "fence_generation": self.fence.fencing_generation,
                "fence_transition": self.fence.transition_digest,
                "lease_contract_version": self.lease_contract_version,
                "eligible_action_types": sorted(self.eligible_action_types),
                "ineligible_provider_action_types": sorted(self.ineligible_provider_action_types),
                "evidence_requirements": sorted(self.evidence_requirements),
                "source_revision_id": self.source_revision_id,
                "creator_principal": self.creator_principal,
                "authentication_evidence_digest": self.authentication_evidence_digest,
                "created_at": instant(aware_utc(self.created_at)),
                "quorum_required": self.quorum_required,
                "required_reviewer_principals": sorted(self.required_reviewer_principals),
            }
        )
        if self.candidate_id != expected:
            raise AuthorizationLifecycleError("candidate_id digest mismatch")


@dataclass(frozen=True, slots=True)
class CandidateReviewRecord:
    """One review by a distinct authenticated human reviewer."""

    review_id: str
    candidate_id: str
    reviewer_principal: str
    decision: ReviewDecision
    reviewed_at: datetime
    authentication_evidence_digest: str
    evidence_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        require_digest("candidate_id", self.candidate_id)
        _require_human("reviewer_principal", self.reviewer_principal)
        require_aware("reviewed_at", self.reviewed_at)
        require_digest("authentication_evidence_digest", self.authentication_evidence_digest)
        for ed in self.evidence_digests:
            require_digest("evidence_digest", ed)
        _require_canonical_distinct("evidence_digests", self.evidence_digests)
        expected = content_digest(
            {
                "candidate_id": self.candidate_id,
                "reviewer_principal": self.reviewer_principal,
                "decision": self.decision.value,
                "reviewed_at": instant(aware_utc(self.reviewed_at)),
                "authentication_evidence_digest": self.authentication_evidence_digest,
                "evidence_digests": self.evidence_digests,
            }
        )
        if self.review_id != expected:
            raise AuthorizationLifecycleError("review_id digest mismatch")


@dataclass(frozen=True, slots=True)
class CandidateRevocationRecord:
    """Explicit revocation by an authenticated human."""

    revocation_id: str
    candidate_id: str
    revoker_principal: str
    revoked_at: datetime
    authentication_evidence_digest: str
    reason: str

    def __post_init__(self) -> None:
        require_digest("revocation_id", self.revocation_id)
        require_digest("candidate_id", self.candidate_id)
        _require_human("revoker_principal", self.revoker_principal)
        require_aware("revoked_at", self.revoked_at)
        require_digest("authentication_evidence_digest", self.authentication_evidence_digest)
        require_text("reason", self.reason)
        expected = content_digest(
            {
                "candidate_id": self.candidate_id,
                "revoker_principal": self.revoker_principal,
                "revoked_at": instant(aware_utc(self.revoked_at)),
                "authentication_evidence_digest": self.authentication_evidence_digest,
                "reason": self.reason,
            }
        )
        if self.revocation_id != expected:
            raise AuthorizationLifecycleError("revocation_id digest mismatch")


@dataclass(frozen=True, slots=True)
class TerminalDenialRecord:
    """Terminal denial. ``terminal_audit_digest`` binds intent and result atomically."""

    denial_id: str
    candidate_id: str
    denial_reason: DenialReason
    denied_at: datetime
    detail: str
    intent_digest: str
    terminal_audit_digest: str
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    def __post_init__(self) -> None:
        require_digest("denial_id", self.denial_id)
        require_digest("candidate_id", self.candidate_id)
        require_aware("denied_at", self.denied_at)
        require_text("detail", self.detail)
        require_digest("intent_digest", self.intent_digest)
        require_digest("terminal_audit_digest", self.terminal_audit_digest)
        expected = content_digest(
            {
                "intent_digest": self.intent_digest,
                "denial_reason": self.denial_reason.value,
                "candidate_id": self.candidate_id,
                "denial_id": self.denial_id,
                "denied_at": instant(aware_utc(self.denied_at)),
                "detail": self.detail,
            }
        )
        if self.terminal_audit_digest != expected:
            raise AuthorizationLifecycleError("terminal_audit_digest mismatch")
        if self.execution_authority is not False or self.promotion_authority is not False:
            raise AuthorizationLifecycleError("authority flags MUST be False")


@dataclass(frozen=True, slots=True)
class CandidateTransition:
    """Hash-chained transition. ``intent_digest`` bound before mutation proves two-phase audit."""

    candidate_id: str
    sequence: int
    kind: CandidateTransitionKind
    actor_ref: str
    authentication_evidence_digest: str
    occurred_at: datetime
    intent_digest: str
    previous_transition_digest: str | None
    transition_digest: str
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    def __post_init__(self) -> None:
        require_digest("candidate_id", self.candidate_id)
        if self.sequence < 1:
            raise AuthorizationLifecycleError("sequence MUST be positive")
        require_text("actor_ref", self.actor_ref)
        require_digest("authentication_evidence_digest", self.authentication_evidence_digest)
        require_aware("occurred_at", self.occurred_at)
        require_digest("intent_digest", self.intent_digest)
        if self.previous_transition_digest is not None:
            require_digest("previous_transition_digest", self.previous_transition_digest)
        if self.transition_digest != content_digest(self._body()):
            raise AuthorizationLifecycleError("CandidateTransition digest mismatch")
        if self.execution_authority is not False or self.promotion_authority is not False:
            raise AuthorizationLifecycleError("authority flags MUST be False")

    def _body(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "sequence": self.sequence,
            "kind": self.kind.value,
            "actor_ref": self.actor_ref,
            "authentication_evidence_digest": self.authentication_evidence_digest,
            "occurred_at": instant(aware_utc(self.occurred_at)),
            "intent_digest": self.intent_digest,
            "previous_transition_digest": self.previous_transition_digest,
        }


@dataclass(frozen=True, slots=True)
class CandidateSnapshot:
    """Deterministic current-state projection from the append-only chain."""

    candidate_id: str
    status: CandidateStatus
    revision_id: str
    fencing_generation: int
    sequence: int
    head_transition_digest: str
    approvals: tuple[str, ...]
    rejections: tuple[str, ...]
    quorum_required: int
    snapshot_digest: str
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    def __post_init__(self) -> None:
        require_digest("candidate_id", self.candidate_id)
        require_digest("revision_id", self.revision_id)
        if self.fencing_generation < 1 or self.sequence < 1:
            raise AuthorizationLifecycleError("fencing_generation and sequence MUST be positive")
        require_digest("head_transition_digest", self.head_transition_digest)
        if self.quorum_required < CANDIDATE_QUORUM:
            raise AuthorizationLifecycleError(f"quorum_required MUST be >= {CANDIDATE_QUORUM}")
        for principal in (*self.approvals, *self.rejections):
            _require_human("snapshot reviewer principal", principal)
        _require_canonical_distinct("approvals", self.approvals)
        _require_canonical_distinct("rejections", self.rejections)
        if set(self.approvals) & set(self.rejections):
            raise AuthorizationLifecycleError(
                "snapshot reviewer MUST NOT appear in approvals and rejections"
            )
        expected = content_digest(
            {
                "candidate_id": self.candidate_id,
                "status": self.status.value,
                "revision_id": self.revision_id,
                "fencing_generation": self.fencing_generation,
                "sequence": self.sequence,
                "head_transition_digest": self.head_transition_digest,
                "approvals": self.approvals,
                "rejections": self.rejections,
                "quorum_required": self.quorum_required,
            }
        )
        if self.snapshot_digest != expected:
            raise AuthorizationLifecycleError("CandidateSnapshot digest mismatch")
        if self.execution_authority is not False or self.promotion_authority is not False:
            raise AuthorizationLifecycleError("authority flags MUST be False")


@dataclass(frozen=True, slots=True)
class PromotionCandidateWriteResult:
    """Result of one candidate store transition."""

    transition: CandidateTransition
    snapshot: CandidateSnapshot
    denial: TerminalDenialRecord | None = None

    def __post_init__(self) -> None:
        if (self.snapshot.status is CandidateStatus.DENIED) != (self.denial is not None):
            raise AuthorizationLifecycleError("denial record present iff snapshot status is DENIED")


@runtime_checkable
class PromotionCandidateStore(Protocol):
    """Atomic persistence. Inert: no production wiring exists."""

    async def create_candidate(
        self, record: PromotionCandidateRecord
    ) -> PromotionCandidateWriteResult: ...

    async def submit_review(
        self, candidate_id: str, review: CandidateReviewRecord
    ) -> PromotionCandidateWriteResult: ...

    async def revoke_candidate(
        self, revocation: CandidateRevocationRecord
    ) -> PromotionCandidateWriteResult: ...

    async def read_candidate(self, candidate_id: str) -> PromotionCandidateRecord | None: ...

    async def read_transitions(self, candidate_id: str) -> tuple[CandidateTransition, ...]: ...

    async def read_snapshot(self, candidate_id: str) -> CandidateSnapshot | None: ...

    async def rebuild_snapshot(self, candidate_id: str) -> CandidateSnapshot | None: ...


__all__ = [
    "CANDIDATE_QUORUM",
    "LEASE_CONTRACT_VERSION",
    "CandidateReviewRecord",
    "CandidateRevocationRecord",
    "CandidateSnapshot",
    "CandidateStatus",
    "CandidateTransition",
    "CandidateTransitionKind",
    "DenialReason",
    "PromotionCandidateRecord",
    "PromotionCandidateStore",
    "PromotionCandidateWriteResult",
    "ReviewDecision",
    "TerminalDenialRecord",
]
