"""StateStore coordinator for immutable human-assignment cases."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from fdai.core.human_assignment.audit import AssignmentAuditKind
from fdai.core.human_assignment.coverage import (
    approval_quorum_satisfied,
    normalize_principal_ref,
    validate_duty_bindings,
    validate_reviewer,
)
from fdai.core.human_assignment.errors import (
    AssignmentConflictError,
    AssignmentPermissionError,
    AssignmentServiceError,
)
from fdai.core.human_assignment.model import (
    AssignmentCase,
    AssignmentIntent,
    AssignmentState,
    EffectKind,
    EffectReceipt,
    ReviewDecision,
    ReviewReceipt,
)
from fdai.core.human_assignment.repository import (
    assignment_case_id,
    create_case_state,
    list_case_states,
    load_case_state,
    persist_case_state,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, has_capability
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class AssignmentCaseService:
    """Validate, persist, audit, and recover assignment cases."""

    store: StateStore

    async def create_case(
        self,
        *,
        principal: Principal,
        intent: AssignmentIntent,
        now: datetime | None = None,
    ) -> AssignmentCase:
        """Create or replay one immutable draft by requester and idempotency key."""

        _require_owner(principal)
        if normalize_principal_ref(principal.oid) != normalize_principal_ref(intent.requester_ref):
            raise AssignmentPermissionError("authenticated principal MUST match requester_ref")
        validate_duty_bindings(intent.duty_bindings)
        case_id = assignment_case_id(intent.requester_ref, intent.idempotency_key)
        requested_at = _timestamp(now)
        requested = AssignmentCase(case_id=case_id, intent=intent)
        return await create_case_state(
            self.store,
            requested,
            actor_ref=principal.oid,
            at=requested_at,
        )

    async def get_case(self, case_id: str) -> AssignmentCase:
        """Load one assignment case by its stable identifier."""

        return await load_case_state(self.store, case_id)

    async def list_case_page(
        self,
        *,
        principal: Principal,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[tuple[AssignmentCase, ...], int]:
        """Return one Owner-only bounded page of immutable case snapshots."""

        _require_owner(principal)
        return await list_case_states(self.store, limit=limit, offset=offset)

    async def submit_for_review(
        self,
        *,
        principal: Principal,
        case_id: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> AssignmentCase:
        """Move a requester's immutable draft into independent review."""

        _require_owner(principal)
        current = await self.get_case(case_id)
        if normalize_principal_ref(principal.oid) != normalize_principal_ref(
            current.intent.requester_ref
        ):
            raise AssignmentPermissionError("only the requester may submit the draft")
        if current.state is not AssignmentState.DRAFT:
            return current
        candidate = replace(
            current,
            state=AssignmentState.PENDING_REVIEW,
            revision=current.revision + 1,
        )
        return await self._persist(
            current,
            candidate,
            expected_revision=expected_revision,
            audit_kind=AssignmentAuditKind.TRANSITIONED,
            actor_ref=principal.oid,
            at=_timestamp(now),
        )

    async def review(
        self,
        *,
        principal: Principal,
        case_id: str,
        expected_revision: int,
        decision: ReviewDecision,
        now: datetime | None = None,
    ) -> AssignmentCase:
        """Append one normalized, independent Owner review decision."""

        current = await self.get_case(case_id)
        existing = _review_by(current, principal.oid)
        if existing is not None:
            if existing.decision is decision:
                return current
            raise AssignmentConflictError("reviewer already recorded a different decision")
        if current.state is not AssignmentState.PENDING_REVIEW:
            raise AssignmentConflictError("assignment case is not pending review")
        validate_reviewer(
            current.intent,
            reviewer_ref=principal.oid,
            reviewer_roles=principal.roles,
            prior_reviews=current.reviews,
        )
        receipt = ReviewReceipt(
            reviewer_ref=principal.oid,
            decision=decision,
            reviewed_at=_timestamp(now),
        )
        reviews = (*current.reviews, receipt)
        target = (
            AssignmentState.REJECTED
            if decision is ReviewDecision.REJECT
            else AssignmentState.APPROVED
            if approval_quorum_satisfied(current.intent, reviews)
            else AssignmentState.PENDING_REVIEW
        )
        candidate = replace(
            current,
            state=target,
            revision=current.revision + 1,
            reviews=reviews,
        )
        return await self._persist(
            current,
            candidate,
            expected_revision=expected_revision,
            audit_kind=AssignmentAuditKind.REVIEWED,
            actor_ref=principal.oid,
            at=receipt.reviewed_at,
        )

    async def open_ownership_pr(
        self,
        *,
        case_id: str,
        expected_revision: int,
        actor_ref: str,
        now: datetime | None = None,
    ) -> AssignmentCase:
        """Begin or retry the reviewed ownership effect."""

        return await self._advance(
            case_id=case_id,
            expected_revision=expected_revision,
            target=AssignmentState.OWNERSHIP_PR_OPEN,
            actor_ref=actor_ref,
            now=now,
        )

    async def begin_iam_apply(
        self,
        *,
        case_id: str,
        expected_revision: int,
        actor_ref: str,
        now: datetime | None = None,
    ) -> AssignmentCase:
        """Begin or retry IAM only after ownership convergence."""

        return await self._advance(
            case_id=case_id,
            expected_revision=expected_revision,
            target=AssignmentState.IAM_APPLYING,
            actor_ref=actor_ref,
            now=now,
        )

    async def record_effect(
        self,
        *,
        case_id: str,
        expected_revision: int,
        receipt: EffectReceipt,
        actor_ref: str,
    ) -> AssignmentCase:
        """Record one effect receipt and advance only its owned state edge."""

        current = await self.get_case(case_id)
        existing = _effect_by(current, receipt.kind)
        if existing is not None:
            if existing == receipt:
                return current
            raise AssignmentConflictError("effect kind already has a different receipt")
        expected_state = (
            AssignmentState.OWNERSHIP_PR_OPEN
            if receipt.kind is EffectKind.OWNERSHIP
            else AssignmentState.IAM_APPLYING
        )
        if current.state is not expected_state:
            raise AssignmentConflictError(
                f"{receipt.kind.value} receipt is not valid in {current.state.value}"
            )
        target = (
            AssignmentState.OWNERSHIP_MERGED
            if receipt.kind is EffectKind.OWNERSHIP
            else AssignmentState.ACTIVE
        )
        candidate = replace(
            current,
            state=target,
            revision=current.revision + 1,
            effect_receipts=(*current.effect_receipts, receipt),
            degraded_reason=None,
        )
        audit_kind = (
            AssignmentAuditKind.EFFECT_RECEIVED
            if receipt.kind is EffectKind.OWNERSHIP
            else AssignmentAuditKind.ACTIVATED
        )
        return await self._persist(
            current,
            candidate,
            expected_revision=expected_revision,
            audit_kind=audit_kind,
            actor_ref=actor_ref,
            at=receipt.received_at,
            effect_kind=receipt.kind,
        )

    async def mark_degraded(
        self,
        *,
        case_id: str,
        expected_revision: int,
        reason_code: str,
        actor_ref: str,
        now: datetime | None = None,
    ) -> AssignmentCase:
        """Hold a post-review case for an explicit forward-repair path."""

        current = await self.get_case(case_id)
        if current.state is AssignmentState.DEGRADED and current.degraded_reason == reason_code:
            return current
        candidate = replace(
            current,
            state=AssignmentState.DEGRADED,
            revision=current.revision + 1,
            degraded_reason=reason_code,
        )
        return await self._persist(
            current,
            candidate,
            expected_revision=expected_revision,
            audit_kind=AssignmentAuditKind.DEGRADED,
            actor_ref=actor_ref,
            at=_timestamp(now),
        )

    async def supersede(
        self,
        *,
        case_id: str,
        expected_revision: int,
        successor_case_id: str,
        actor_ref: str,
        now: datetime | None = None,
    ) -> AssignmentCase:
        """Close immutable history in favor of a newly requested intent."""

        current = await self.get_case(case_id)
        if (
            current.state is AssignmentState.SUPERSEDED
            and current.superseded_by == successor_case_id
        ):
            return current
        candidate = replace(
            current,
            state=AssignmentState.SUPERSEDED,
            revision=current.revision + 1,
            superseded_by=successor_case_id,
        )
        return await self._persist(
            current,
            candidate,
            expected_revision=expected_revision,
            audit_kind=AssignmentAuditKind.SUPERSEDED,
            actor_ref=actor_ref,
            at=_timestamp(now),
        )

    async def _advance(
        self,
        *,
        case_id: str,
        expected_revision: int,
        target: AssignmentState,
        actor_ref: str,
        now: datetime | None,
    ) -> AssignmentCase:
        current = await self.get_case(case_id)
        if current.state is target:
            return current
        candidate = replace(
            current,
            state=target,
            revision=current.revision + 1,
            degraded_reason=None,
        )
        return await self._persist(
            current,
            candidate,
            expected_revision=expected_revision,
            audit_kind=AssignmentAuditKind.TRANSITIONED,
            actor_ref=actor_ref,
            at=_timestamp(now),
        )

    async def _persist(
        self,
        current: AssignmentCase,
        candidate: AssignmentCase,
        *,
        expected_revision: int,
        audit_kind: AssignmentAuditKind,
        actor_ref: str,
        at: datetime,
        effect_kind: EffectKind | None = None,
    ) -> AssignmentCase:
        return await persist_case_state(
            self.store,
            current,
            candidate,
            expected_revision=expected_revision,
            audit_kind=audit_kind,
            actor_ref=actor_ref,
            at=at,
            effect_kind=effect_kind,
        )


def _require_owner(principal: Principal) -> None:
    if not has_capability(principal.roles, Capability.MANAGE_GROUP_MEMBERSHIP):
        raise AssignmentPermissionError("manage-group-membership capability is required")


def _review_by(case: AssignmentCase, reviewer_ref: str) -> ReviewReceipt | None:
    normalized = normalize_principal_ref(reviewer_ref)
    return next(
        (
            receipt
            for receipt in case.reviews
            if normalize_principal_ref(receipt.reviewer_ref) == normalized
        ),
        None,
    )


def _effect_by(case: AssignmentCase, kind: EffectKind) -> EffectReceipt | None:
    return next((receipt for receipt in case.effect_receipts if receipt.kind is kind), None)


def _timestamp(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise AssignmentServiceError("assignment timestamp MUST be timezone-aware")
    return timestamp.astimezone(UTC)


__all__ = [
    "AssignmentAuditKind",
    "AssignmentCaseService",
    "AssignmentConflictError",
    "AssignmentPermissionError",
    "AssignmentServiceError",
]
