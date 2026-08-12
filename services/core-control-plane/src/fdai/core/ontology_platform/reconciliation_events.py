"""Compact typed events for production effect reconciliation bindings.

The wire request carries exact identities and target revisions, not an ontology release or
mutation plan body. A composition-owned resolver restores those local immutable artifacts before
the coordinator can evaluate the independently authenticated observation.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from fdai.shared.contracts.models import (
    ContractBase,
    OntologyActionType,
    OntologyRelease,
    OntologyReleaseRef,
    OntologyTypeRef,
    SemVer,
)

from .kinetics import MutationPlan, ReconciliationStatus
from .reconciliation_contracts import (
    AuthenticatedObservationContext,
    EffectObservationEnvelope,
    EffectReconciliationRequest,
    ReconciliationOutcome,
    ReconciliationRecommendation,
    reconciliation_content_digest,
)

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_IDENTITY_PATTERN = r"^reconciliation:[a-f0-9]{64}$"
_ATTEMPT_PATTERN = r"^reconciliation-attempt:[a-f0-9]{64}$"
_RECOMMENDATION_PATTERN = r"^reconciliation-next-step:[a-f0-9]{64}$"


class ReconciliationTargetRevision(ContractBase):
    """Compact exact target identity retained across the reconciliation wire boundary."""

    object_id: Annotated[str, Field(min_length=1, max_length=512)]
    type_ref: OntologyTypeRef
    revision: int = Field(ge=1)


class EffectReconciliationRequestEvent(ContractBase):
    """Authenticated observation request without duplicated release or mutation-plan bodies."""

    schema_version: SemVer = "1.0.0"
    event_type: Literal["ontology.effect_reconciliation.requested.v1"] = (
        "ontology.effect_reconciliation.requested.v1"
    )
    reconciliation_id: Annotated[str, Field(pattern=_IDENTITY_PATTERN)]
    observation_attempt_id: Annotated[str, Field(pattern=_ATTEMPT_PATTERN)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    ontology_release_ref: OntologyReleaseRef
    action_type_ref: OntologyTypeRef
    plan_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    target_revisions: Annotated[tuple[ReconciliationTargetRevision, ...], Field(min_length=1)]
    evidence: EffectObservationEnvelope
    observation_context: AuthenticatedObservationContext
    deadline: datetime
    evaluated_at: datetime
    event_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @classmethod
    def from_request(
        cls,
        request: EffectReconciliationRequest,
        *,
        observation_context: AuthenticatedObservationContext,
    ) -> Self:
        """Create a compact event from a fully validated local reconciliation request."""

        target_revisions = tuple(
            ReconciliationTargetRevision(
                object_id=target.object_id,
                type_ref=target.type_ref,
                revision=target.revision,
            )
            for target in request.plan.targets
        )
        prototype = cls.model_construct(
            reconciliation_id=request.reconciliation_id,
            observation_attempt_id=request.observation_attempt_id,
            correlation_id=request.correlation_id,
            ontology_release_ref=request.evidence.ontology_release_ref,
            action_type_ref=request.plan.action_type_ref,
            plan_digest=request.plan.digest,
            target_revisions=target_revisions,
            evidence=request.evidence,
            observation_context=observation_context,
            deadline=request.deadline,
            evaluated_at=request.evaluated_at,
            event_digest="sha256:" + "0" * 64,
        )
        return cls(
            reconciliation_id=request.reconciliation_id,
            observation_attempt_id=request.observation_attempt_id,
            correlation_id=request.correlation_id,
            ontology_release_ref=request.evidence.ontology_release_ref,
            action_type_ref=request.plan.action_type_ref,
            plan_digest=request.plan.digest,
            target_revisions=target_revisions,
            evidence=request.evidence,
            observation_context=observation_context,
            deadline=request.deadline,
            evaluated_at=request.evaluated_at,
            event_digest=reconciliation_content_digest(
                prototype.model_dump(mode="json", exclude={"event_digest"})
            ),
        )

    @model_validator(mode="after")
    def _event_is_canonical(self) -> EffectReconciliationRequestEvent:
        if (
            self.deadline.tzinfo is None
            or self.deadline.utcoffset() is None
            or self.evaluated_at.tzinfo is None
            or self.evaluated_at.utcoffset() is None
        ):
            raise ValueError("reconciliation request event times MUST be timezone-aware")
        target_keys = tuple(
            (target.object_id, target.type_ref.kind.value, target.type_ref.name)
            for target in self.target_revisions
        )
        if tuple(sorted(set(target_keys))) != target_keys:
            raise ValueError("reconciliation target revisions MUST be sorted and unique")
        if (
            self.evidence.correlation_id != self.correlation_id
            or self.evidence.ontology_release_ref != self.ontology_release_ref
            or self.evidence.action_type_ref != self.action_type_ref
            or self.evidence.plan_digest != self.plan_digest
        ):
            raise ValueError("reconciliation request event evidence bindings do not match")
        expected = reconciliation_content_digest(
            self.model_dump(mode="json", exclude={"event_digest"})
        )
        if self.event_digest != expected:
            raise ValueError("reconciliation request event digest does not match content")
        return self

    def bind(
        self,
        *,
        plan: MutationPlan,
        action_type: OntologyActionType,
        active_release: OntologyRelease,
    ) -> EffectReconciliationRequest:
        """Bind resolver-owned immutable bodies and reject stale or substituted artifacts."""

        target_revisions = tuple(
            ReconciliationTargetRevision(
                object_id=target.object_id,
                type_ref=target.type_ref,
                revision=target.revision,
            )
            for target in plan.targets
        )
        if (
            active_release.ref() != self.ontology_release_ref
            or plan.action_type_ref != self.action_type_ref
            or plan.digest != self.plan_digest
            or target_revisions != self.target_revisions
            or action_type.name != self.action_type_ref.name
            or action_type.version != self.action_type_ref.version
        ):
            raise ValueError("resolved reconciliation artifacts do not match the request event")
        request = EffectReconciliationRequest.create(
            correlation_id=self.correlation_id,
            plan=plan,
            action_type=action_type,
            evidence=self.evidence,
            deadline=self.deadline,
            evaluated_at=self.evaluated_at,
        )
        if (
            request.reconciliation_id != self.reconciliation_id
            or request.observation_attempt_id != self.observation_attempt_id
        ):
            raise ValueError("resolved reconciliation request identities do not match the event")
        return request


class EffectReconciliationResultEvent(ContractBase):
    """Compact terminal or held result preserving observation separation-of-duty evidence."""

    schema_version: SemVer = "1.0.0"
    event_type: Literal["ontology.effect_reconciliation.result.v1"] = (
        "ontology.effect_reconciliation.result.v1"
    )
    reconciliation_id: Annotated[str, Field(pattern=_IDENTITY_PATTERN)]
    observation_attempt_id: Annotated[str, Field(pattern=_ATTEMPT_PATTERN)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    ontology_release_ref: OntologyReleaseRef
    action_type_ref: OntologyTypeRef
    plan_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    target_revisions: Annotated[tuple[ReconciliationTargetRevision, ...], Field(min_length=1)]
    observer_identity: Annotated[str, Field(min_length=1, max_length=512)]
    executor_identity: Annotated[str, Field(min_length=1, max_length=512)]
    source_identity: Annotated[str, Field(min_length=1, max_length=512)]
    source_credential_lineage: Annotated[str, Field(min_length=1, max_length=512)]
    request_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    observation_context_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    verification_receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    recommendation_idempotency_key: Annotated[str, Field(pattern=_RECOMMENDATION_PATTERN)]
    status: ReconciliationStatus
    terminal: bool
    result_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @classmethod
    def from_outcome(cls, outcome: ReconciliationOutcome) -> Self:
        """Project one coordinator outcome into its bounded event result."""

        request = outcome.request
        context = outcome.observation_context
        target_revisions = tuple(
            ReconciliationTargetRevision(
                object_id=target.object_id,
                type_ref=target.type_ref,
                revision=target.revision,
            )
            for target in request.plan.targets
        )
        prototype = cls.model_construct(
            reconciliation_id=outcome.reconciliation_id,
            observation_attempt_id=outcome.observation_attempt_id,
            correlation_id=outcome.correlation_id,
            ontology_release_ref=request.evidence.ontology_release_ref,
            action_type_ref=request.plan.action_type_ref,
            plan_digest=request.plan.digest,
            target_revisions=target_revisions,
            observer_identity=context.observer_identity,
            executor_identity=context.executor_identity,
            source_identity=context.source_identity,
            source_credential_lineage=context.source_credential_lineage,
            request_digest=outcome.request_digest,
            receipt_digest=outcome.receipt_digest,
            observation_context_digest=outcome.observation_context_digest,
            verification_receipt_digest=outcome.verification_receipt_digest,
            recommendation_idempotency_key=outcome.recommendation.idempotency_key,
            status=outcome.receipt.status,
            terminal=outcome.terminal,
            result_digest="sha256:" + "0" * 64,
        )
        return cls(
            reconciliation_id=outcome.reconciliation_id,
            observation_attempt_id=outcome.observation_attempt_id,
            correlation_id=outcome.correlation_id,
            ontology_release_ref=request.evidence.ontology_release_ref,
            action_type_ref=request.plan.action_type_ref,
            plan_digest=request.plan.digest,
            target_revisions=target_revisions,
            observer_identity=context.observer_identity,
            executor_identity=context.executor_identity,
            source_identity=context.source_identity,
            source_credential_lineage=context.source_credential_lineage,
            request_digest=outcome.request_digest,
            receipt_digest=outcome.receipt_digest,
            observation_context_digest=outcome.observation_context_digest,
            verification_receipt_digest=outcome.verification_receipt_digest,
            recommendation_idempotency_key=outcome.recommendation.idempotency_key,
            status=outcome.receipt.status,
            terminal=outcome.terminal,
            result_digest=reconciliation_content_digest(
                prototype.model_dump(mode="json", exclude={"result_digest"})
            ),
        )

    @model_validator(mode="after")
    def _result_is_canonical(self) -> EffectReconciliationResultEvent:
        if self.terminal == (self.status is ReconciliationStatus.UNSCORABLE):
            raise ValueError("only matched, mismatched, and timed_out results are terminal")
        expected = reconciliation_content_digest(
            self.model_dump(mode="json", exclude={"result_digest"})
        )
        if self.result_digest != expected:
            raise ValueError("reconciliation result digest does not match content")
        return self


class ReconciliationOutboxEvent(ContractBase):
    """Atomic publication payload containing the result and proposal-only next event."""

    schema_version: SemVer = "1.0.0"
    event_type: Literal["ontology.effect_reconciliation.outbox.v1"] = (
        "ontology.effect_reconciliation.outbox.v1"
    )
    idempotency_key: Annotated[str, Field(pattern=_RECOMMENDATION_PATTERN)]
    result: EffectReconciliationResultEvent
    recommendation: ReconciliationRecommendation
    proposal_only: Literal[True] = True
    grants_authority: Literal[False] = False

    @classmethod
    def from_outcome(cls, outcome: ReconciliationOutcome) -> Self:
        """Create the one replay-stable outbox event for a terminal outcome."""

        if not outcome.terminal:
            raise ValueError("only terminal reconciliation outcomes create outbox events")
        return cls(
            idempotency_key=outcome.recommendation.idempotency_key,
            result=EffectReconciliationResultEvent.from_outcome(outcome),
            recommendation=outcome.recommendation,
        )

    @model_validator(mode="after")
    def _outbox_is_bound(self) -> ReconciliationOutboxEvent:
        if (
            self.idempotency_key != self.recommendation.idempotency_key
            or self.result.reconciliation_id != self.recommendation.reconciliation_id
            or self.result.observation_attempt_id != self.recommendation.observation_attempt_id
            or self.result.correlation_id != self.recommendation.correlation_id
            or self.result.ontology_release_ref != self.recommendation.ontology_release_ref
            or self.result.action_type_ref != self.recommendation.action_type_ref
            or self.result.plan_digest != self.recommendation.plan_digest
            or self.result.request_digest != self.recommendation.request_digest
            or self.result.receipt_digest != self.recommendation.receipt_digest
            or self.result.observation_context_digest
            != self.recommendation.observation_context_digest
            or self.result.verification_receipt_digest
            != self.recommendation.verification_receipt_digest
        ):
            raise ValueError("reconciliation outbox result and recommendation are not bound")
        return self


class ReconciliationOutboxDeliveryState(StrEnum):
    """Durable publication state for one terminal reconciliation outbox event."""

    PENDING = "pending"
    CLAIMED = "claimed"
    PUBLISHED = "published"


class ReconciliationOutboxRecord(ContractBase):
    """Lease-fenced durable delivery record retaining the immutable outbox event."""

    schema_version: SemVer = "1.0.0"
    event: ReconciliationOutboxEvent
    state: ReconciliationOutboxDeliveryState = ReconciliationOutboxDeliveryState.PENDING
    attempts: int = Field(default=0, ge=0)
    available_at: datetime | None = None
    claimant_id: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    lease_until: datetime | None = None
    published_at: datetime | None = None

    @model_validator(mode="after")
    def _delivery_state_is_consistent(self) -> ReconciliationOutboxRecord:
        timestamps = tuple(
            value
            for value in (self.available_at, self.lease_until, self.published_at)
            if value is not None
        )
        if any(value.tzinfo is None or value.utcoffset() is None for value in timestamps):
            raise ValueError("reconciliation outbox timestamps MUST be timezone-aware")
        claimed = self.state is ReconciliationOutboxDeliveryState.CLAIMED
        published = self.state is ReconciliationOutboxDeliveryState.PUBLISHED
        if claimed != (self.claimant_id is not None and self.lease_until is not None):
            raise ValueError("claimed reconciliation outbox state requires one lease owner")
        if not claimed and (self.claimant_id is not None or self.lease_until is not None):
            raise ValueError("unclaimed reconciliation outbox state MUST NOT retain a lease")
        if published != (self.published_at is not None):
            raise ValueError("published reconciliation outbox state requires published_at")
        return self


__all__ = [
    "EffectReconciliationRequestEvent",
    "EffectReconciliationResultEvent",
    "ReconciliationOutboxDeliveryState",
    "ReconciliationOutboxEvent",
    "ReconciliationOutboxRecord",
    "ReconciliationTargetRevision",
]
