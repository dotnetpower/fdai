"""StateStore coordinator for immutable human-assignment cases."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from fdai_service_contracts.human_access_execution import (
    HumanAccessExecutionMaterial,
    HumanAccessPreparation,
    human_access_record_digest,
)

from fdai.core.human_assignment.audit import AssignmentAuditKind
from fdai.core.human_assignment.command_receipt import AssignmentCommandReceipt
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
from fdai.core.human_assignment.revocation_target import require_revocation_target
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
        command_receipt: AssignmentCommandReceipt | None = None,
    ) -> AssignmentCase:
        """Create or replay one immutable draft by requester and idempotency key."""

        _require_owner(principal)
        if normalize_principal_ref(principal.oid) != normalize_principal_ref(intent.requester_ref):
            raise AssignmentPermissionError("authenticated principal MUST match requester_ref")
        validate_duty_bindings(intent.duty_bindings)
        case_id = assignment_case_id(intent.requester_ref, intent.idempotency_key)
        requested_at = _timestamp(now)
        requested = AssignmentCase(
            case_id=case_id,
            intent=intent,
            command_receipts=(command_receipt,) if command_receipt is not None else (),
        )
        if (
            intent.revocation is not None
            and await self.store.read_state(f"human_assignment:case:{case_id}") is None
        ):
            await require_revocation_target(self.store, intent, revocation_case_id=case_id)
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
        command_receipt: AssignmentCommandReceipt | None = None,
    ) -> AssignmentCase:
        """Move a requester's immutable draft into independent review."""

        _require_owner(principal)
        current = await self.get_case(case_id)
        if normalize_principal_ref(principal.oid) != normalize_principal_ref(
            current.intent.requester_ref
        ):
            raise AssignmentPermissionError("only the requester may submit the draft")
        if current.state is not AssignmentState.DRAFT:
            _require_command_replay(current, command_receipt)
            return current
        candidate = replace(
            current,
            state=AssignmentState.PENDING_REVIEW,
            revision=current.revision + 1,
            command_receipts=_command_receipts(current, command_receipt),
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
        command_receipt: AssignmentCommandReceipt | None = None,
    ) -> AssignmentCase:
        """Append one normalized, independent Owner review decision."""

        current = await self.get_case(case_id)
        existing = _review_by(current, principal.oid)
        if existing is not None:
            if existing.decision is decision:
                _require_command_replay(current, command_receipt)
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
            command_receipts=_command_receipts(current, command_receipt),
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
        """Begin IAM after ownership for grants; hold the old assignment first for removals.

        This coordination edge is not execution authorization. Provider dispatch still belongs
        to Thor behind current approval, safeguards, and independently reviewed promotion.
        """

        current = await self.get_case(case_id)
        if current.revision != expected_revision or isinstance(expected_revision, bool):
            raise AssignmentConflictError("IAM transition revision is stale")
        if current.intent.revocation is not None:
            if current.state not in {
                AssignmentState.APPROVED,
                AssignmentState.IAM_APPLYING,
                AssignmentState.DEGRADED,
            } or not approval_quorum_satisfied(current.intent, current.reviews):
                raise AssignmentConflictError("revocation requires its own independent review")
            if EffectKind.IAM in current.effect_kinds:
                raise AssignmentConflictError("verified revocation cannot be dispatched again")
            await self._hold_revocation_target(current, actor_ref=actor_ref, at=_timestamp(now))

        return await self._advance(
            case_id=case_id,
            expected_revision=expected_revision,
            target=AssignmentState.IAM_APPLYING,
            actor_ref=actor_ref,
            now=now,
        )

    async def prepare_human_access(
        self, *, material: HumanAccessExecutionMaterial, actor_ref: str, now: datetime
    ) -> AssignmentCase:
        """Record exact pre-approved Action lineage after Saga/Var checks, without executing.

        Original expected_revision stays r; this case advances atomically to r+1
        with its material/source binding. Exact restart replay cannot rebind it.
        Only the existing revocation target hold is a preceding recoverable edge.
        """
        if material.inverse is not None:
            return await self._prepare_human_access_inverse(
                material=material, actor_ref=actor_ref, now=now
            )
        action = material.action()
        case_id = action.params["case_id"]
        current = await self.get_case(case_id)
        binding = HumanAccessPreparation(
            material_digest=material.digest,
            source_case_digest=material.case_record_digest,
            source_revision=action.params["expected_revision"],
            prepared_revision=action.params["expected_revision"] + 1,
        )
        if current.iam_preparation is not None:
            if current.iam_preparation == binding:
                return current
            raise AssignmentConflictError(
                "IAM preparation already belongs to another reviewed Action"
            )
        if not material.recorded_at <= _timestamp(now) < material.expires_at:
            raise AssignmentConflictError("IAM material review window expired before preparation")
        revoke = current.intent.revocation is not None
        if (
            current.revision != binding.source_revision
            or human_access_record_digest(current.to_dict()) != binding.source_case_digest
            or current.state
            is not (AssignmentState.APPROVED if revoke else AssignmentState.OWNERSHIP_MERGED)
        ):
            raise AssignmentConflictError("IAM preparation source case changed")
        if (
            material.subject_id != current.intent.subject.subject_id
            or material.requester_ref != current.intent.requester_ref
            or material.requested_role != current.intent.requested_role.value
            or (action.action_type == "ops.revoke-human-access") != revoke
            or not approval_quorum_satisfied(current.intent, current.reviews)
        ):
            raise AssignmentConflictError("IAM preparation does not match the reviewed case")
        if revoke:
            await self._hold_revocation_target(current, actor_ref=actor_ref, at=_timestamp(now))
        candidate = replace(
            current,
            state=AssignmentState.IAM_APPLYING,
            revision=binding.prepared_revision,
            iam_preparation=binding,
            degraded_reason=None,
        )
        return await self._persist(
            current,
            candidate,
            expected_revision=current.revision,
            audit_kind=AssignmentAuditKind.TRANSITIONED,
            actor_ref=actor_ref,
            at=_timestamp(now),
        )

    async def _prepare_human_access_inverse(
        self, *, material: HumanAccessExecutionMaterial, actor_ref: str, now: datetime
    ) -> AssignmentCase:
        """Hold fresh inverse preparation without rewriting original intent, effect or approval."""
        inverse = material.inverse
        if inverse is None:
            raise AssignmentConflictError("IAM inverse material is missing")
        action = material.action()
        current = await self.get_case(action.params["case_id"])
        binding = HumanAccessPreparation(
            material_digest=material.digest,
            source_case_digest=material.case_record_digest,
            source_revision=action.params["expected_revision"],
            prepared_revision=action.params["expected_revision"] + 1,
        )
        if current.iam_recovery_preparation is not None:
            if current.iam_recovery_preparation == binding:
                return current
            raise AssignmentConflictError("IAM inverse already belongs to another reviewed Action")
        if (
            not material.recorded_at <= _timestamp(now) < material.expires_at
            or current.state is not AssignmentState.DEGRADED
            or current.revision != binding.source_revision
            or human_access_record_digest(current.to_dict()) != material.case_record_digest
            or current.iam_preparation is None
            or current.iam_preparation.material_digest != inverse.original_material_digest
            or current.intent.subject.subject_id != material.subject_id
        ):
            raise AssignmentConflictError("IAM inverse preparation source changed")
        return await self._persist(
            current,
            replace(
                current,
                revision=binding.prepared_revision,
                iam_recovery_preparation=binding,
            ),
            expected_revision=current.revision,
            audit_kind=AssignmentAuditKind.TRANSITIONED,
            actor_ref=actor_ref,
            at=_timestamp(now),
        )

    async def record_human_access_recovery(
        self, *, material: HumanAccessExecutionMaterial, receipt: EffectReceipt, actor_ref: str
    ) -> AssignmentCase:
        """Retain observed inverse without restoring assignment, duty or contribution authority."""
        current = await self.get_case(material.action().params["case_id"])
        preparation = current.iam_recovery_preparation
        if current.iam_recovery_effect is not None:
            if current.iam_recovery_effect == receipt:
                return current
            raise AssignmentConflictError("IAM inverse already has a different effect")
        if (
            material.inverse is None
            or preparation is None
            or preparation.material_digest != material.digest
            or current.revision != preparation.prepared_revision
            or current.state is not AssignmentState.DEGRADED
        ):
            raise AssignmentConflictError("IAM inverse effect source changed")
        return await self._persist(
            current,
            replace(current, revision=current.revision + 1, iam_recovery_effect=receipt),
            expected_revision=current.revision,
            audit_kind=AssignmentAuditKind.EFFECT_RECEIVED,
            actor_ref=actor_ref,
            at=receipt.received_at,
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
                if current.state is AssignmentState.REVOKED:
                    await self.close_revocation_target(case_id=case_id, actor_ref=actor_ref)
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
        revoke = current.intent.revocation is not None
        if revoke:
            await require_revocation_target(
                self.store, current.intent, revocation_case_id=case_id, allow_held=True
            )
        target = (
            (AssignmentState.REVOKED if revoke else AssignmentState.OWNERSHIP_MERGED)
            if receipt.kind is EffectKind.OWNERSHIP
            else (AssignmentState.IAM_REVOKED if revoke else AssignmentState.ACTIVE)
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
            if receipt.kind is EffectKind.OWNERSHIP or revoke
            else AssignmentAuditKind.ACTIVATED
        )
        result = await self._persist(
            current,
            candidate,
            expected_revision=expected_revision,
            audit_kind=audit_kind,
            actor_ref=actor_ref,
            at=receipt.received_at,
            effect_kind=receipt.kind,
        )
        if result.state is AssignmentState.REVOKED:
            await self.close_revocation_target(case_id=case_id, actor_ref=actor_ref)
        return result

    async def close_revocation_target(self, *, case_id: str, actor_ref: str) -> None:
        """Close only this removal's old-case hold after both independently recorded effects.

        The writes are intentionally recoverable, not claimed atomic across two cases. Failure
        leaves the original held, never active, and exact merge replay repairs the closure.
        """
        removal = await self.get_case(case_id)
        target = removal.intent.revocation
        if target is None or removal.state is not AssignmentState.REVOKED:
            raise AssignmentConflictError("original assignment closure requires verified removal")
        old = await self.get_case(target.case_id)
        if (
            old.state is AssignmentState.SUPERSEDED
            and old.superseded_by == removal.case_id
            and old.revocation_case_id == removal.case_id
        ):
            return
        old = await require_revocation_target(
            self.store, removal.intent, revocation_case_id=removal.case_id, allow_held=True
        )
        if old.revocation_case_id != removal.case_id:
            raise AssignmentConflictError("original assignment has no matching revocation hold")
        await self.supersede(
            case_id=old.case_id,
            expected_revision=old.revision,
            successor_case_id=removal.case_id,
            actor_ref=actor_ref,
        )

    async def _hold_revocation_target(
        self, removal: AssignmentCase, *, actor_ref: str, at: datetime
    ) -> None:
        old = await require_revocation_target(
            self.store, removal.intent, revocation_case_id=removal.case_id, allow_held=True
        )
        if old.revocation_case_id == removal.case_id:
            return
        await self._persist(
            old,
            replace(
                old,
                state=AssignmentState.DEGRADED,
                revision=old.revision + 1,
                degraded_reason="revocation_pending",
                revocation_case_id=removal.case_id,
            ),
            expected_revision=old.revision,
            audit_kind=AssignmentAuditKind.DEGRADED,
            actor_ref=actor_ref,
            at=at,
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


def _command_receipts(
    case: AssignmentCase, receipt: AssignmentCommandReceipt | None
) -> tuple[AssignmentCommandReceipt, ...]:
    return case.command_receipts + ((receipt,) if receipt is not None else ())


def _require_command_replay(case: AssignmentCase, receipt: AssignmentCommandReceipt | None) -> None:
    if receipt is not None and receipt not in case.command_receipts:
        raise AssignmentConflictError("assignment transition belongs to a different command")


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
