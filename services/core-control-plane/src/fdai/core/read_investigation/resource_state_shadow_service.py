"""Read-only orchestration for exact resource-state shadow comparisons.

The existing :class:`ReadInvestigationResult` remains the sole response
authority. This service only compares it with a separately verified semantic
query and emits a non-authoritative observation receipt.
"""

from __future__ import annotations

import logging

from fdai.core.ontology_platform.evidence_conflict import (
    EvidenceConflictCandidatePublisher,
    EvidenceConflictCurrentReader,
    EvidenceConflictRevision,
    EvidenceConflictStatus,
    EvidenceSourceLineage,
    evidence_conflict_slot_ref,
)
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.core.ontology_platform.query_profiles import QueryProfile
from fdai.core.ontology_platform.semantic_plans import VerifiedSemanticPlan
from fdai.core.ontology_platform.semantic_query import SemanticQueryReceipt
from fdai.core.read_investigation.models import ReadInvestigationResult
from fdai.core.read_investigation.resource_state_shadow_evidence import (
    NormalizedResourceStateObservation,
    ResourceIdentityCanonicalizer,
    cross_source_state_fact,
    existing_input_digest,
    extract_existing_state,
    extract_semantic_state,
    invocation_digest,
    observation_mismatches,
    rejected_input_digest,
    semantic_lineage_matches,
)
from fdai.core.read_investigation.resource_state_shadow_models import (
    ShadowComparisonAttempt,
    ShadowComparisonOutcome,
    ShadowComparisonReason,
    ShadowComparisonReceipt,
    ShadowReceiptPersistence,
    ShadowSinkErrorKind,
    build_shadow_receipt,
    select_shadow_outcome,
)
from fdai.core.read_investigation.shadow_sink import (
    ShadowComparisonSink,
    ShadowReceiptIdentityConflictError,
    ShadowSinkAppendResult,
)
from fdai.shared.providers.state_evidence import StateFactMetadata

_LOG = logging.getLogger(__name__)


class ShadowResourceStateComparisonService:
    """Compare two read-only state observations and append a shadow receipt.

    Sink failure is returned as attempt metadata and never changes, retries, or
    replaces the existing investigation result.
    """

    def __init__(
        self,
        *,
        sink: ShadowComparisonSink,
        identity_canonicalizer: ResourceIdentityCanonicalizer | None = None,
        evidence_conflict_reader: EvidenceConflictCurrentReader | None = None,
        evidence_conflict_publisher: EvidenceConflictCandidatePublisher | None = None,
    ) -> None:
        self._sink = sink
        self._identity_canonicalizer = identity_canonicalizer
        self._evidence_conflict_reader = evidence_conflict_reader
        self._evidence_conflict_publisher = evidence_conflict_publisher

    async def compare(
        self,
        *,
        existing_result: ReadInvestigationResult,
        query_result: SecuredObjectSetQueryResult,
        semantic_receipt: SemanticQueryReceipt,
        query_profile: QueryProfile,
        semantic_plan: VerifiedSemanticPlan,
        principal_ref: str,
        correlation_ref: str,
        attempt_latency_ms: float | None = None,
    ) -> ShadowComparisonAttempt:
        """Record a comparison while preserving the original response object."""

        receipt, adjudicated, existing, semantic = _compare_receipt(
            existing_result=existing_result,
            query_result=query_result,
            semantic_receipt=semantic_receipt,
            query_profile=query_profile,
            semantic_plan=semantic_plan,
            principal_ref=principal_ref,
            correlation_ref=correlation_ref,
            identity_canonicalizer=self._identity_canonicalizer,
        )
        try:
            append_result = await self._sink.append(receipt)
        except ShadowReceiptIdentityConflictError:
            return _failed_attempt(
                existing_result=existing_result,
                receipt=receipt,
                correlation_ref=correlation_ref,
                attempt_latency_ms=attempt_latency_ms,
                cross_source_state_fact=adjudicated,
                error_kind=ShadowSinkErrorKind.IDENTITY_CONFLICT,
            )
        except Exception as exc:  # noqa: BLE001 - shadow persistence cannot rewrite response
            del exc
            return _failed_attempt(
                existing_result=existing_result,
                receipt=receipt,
                correlation_ref=correlation_ref,
                attempt_latency_ms=attempt_latency_ms,
                cross_source_state_fact=adjudicated,
                error_kind=ShadowSinkErrorKind.APPEND_FAILED,
            )
        if not isinstance(append_result, ShadowSinkAppendResult):
            return _failed_attempt(
                existing_result=existing_result,
                receipt=receipt,
                correlation_ref=correlation_ref,
                attempt_latency_ms=attempt_latency_ms,
                cross_source_state_fact=adjudicated,
                error_kind=ShadowSinkErrorKind.INVALID_RESULT,
            )
        if append_result.receipt != receipt:
            return _failed_attempt(
                existing_result=existing_result,
                receipt=receipt,
                correlation_ref=correlation_ref,
                attempt_latency_ms=attempt_latency_ms,
                cross_source_state_fact=adjudicated,
                error_kind=ShadowSinkErrorKind.IDENTITY_CONFLICT,
            )
        evidence_conflict_revision = await self._publish_evidence_conflict(
            receipt=receipt,
            existing=existing,
            semantic=semantic,
            generation_ref=query_result.receipt.source_generation,
        )
        return ShadowComparisonAttempt(
            authoritative_result=existing_result,
            receipt=append_result.receipt,
            persistence=append_result.persistence,
            attempt_latency_ms=attempt_latency_ms,
            cross_source_state_fact=adjudicated,
            evidence_conflict_revision=evidence_conflict_revision,
        )

    async def _publish_evidence_conflict(
        self,
        *,
        receipt: ShadowComparisonReceipt,
        existing: NormalizedResourceStateObservation | None,
        semantic: NormalizedResourceStateObservation | None,
        generation_ref: str | None,
    ) -> EvidenceConflictRevision | None:
        reader = self._evidence_conflict_reader
        publisher = self._evidence_conflict_publisher
        if (
            reader is None
            or publisher is None
            or generation_ref is None
            or existing is None
            or semantic is None
        ):
            return None
        slot_ref = evidence_conflict_slot_ref(
            target_ref=existing.resource_identity,
            scope_ref="scope:resource-state",
            generation_ref=generation_ref,
        )
        current = await reader.current(slot_ref)
        if receipt.outcome is ShadowComparisonOutcome.MATCH:
            if current is None or current.status is EvidenceConflictStatus.RESOLVED:
                return None
            status = EvidenceConflictStatus.RESOLVED
            conflicting_fields: tuple[str, ...] = ()
        elif receipt.cross_source_conflicts:
            status = EvidenceConflictStatus.ACTIVE
            conflicting_fields = receipt.cross_source_conflicts
        else:
            return None
        revision = EvidenceConflictRevision.create(
            status=status,
            target_ref=existing.resource_identity,
            scope_ref="scope:resource-state",
            generation_ref=generation_ref,
            semantic_refs=("runtime.vm.power_state",),
            conflicting_fields=conflicting_fields,
            source_a=_evidence_lineage(existing),
            source_b=_evidence_lineage(semantic),
            supersedes_revision_ref=current.revision_ref if current is not None else None,
        )
        await publisher.publish(revision)
        return revision


def _compare_receipt(
    *,
    existing_result: ReadInvestigationResult,
    query_result: SecuredObjectSetQueryResult,
    semantic_receipt: SemanticQueryReceipt,
    query_profile: QueryProfile,
    semantic_plan: VerifiedSemanticPlan,
    principal_ref: str,
    correlation_ref: str,
    identity_canonicalizer: ResourceIdentityCanonicalizer | None,
) -> tuple[
    ShadowComparisonReceipt,
    StateFactMetadata | None,
    NormalizedResourceStateObservation | None,
    NormalizedResourceStateObservation | None,
]:
    reasons: set[ShadowComparisonReason] = set()
    try:
        existing_digest = existing_input_digest(existing_result)
    except (TypeError, ValueError):
        existing_digest = rejected_input_digest(source="existing")
        reasons.add(ShadowComparisonReason.EXISTING_EVIDENCE_MALFORMED)
    try:
        semantic_invocation_digest = invocation_digest(semantic_receipt)
    except (TypeError, ValueError):
        semantic_invocation_digest = rejected_input_digest(source="semantic_invocation")
        reasons.add(ShadowComparisonReason.SEMANTIC_LINEAGE_MISMATCH)
    semantic_digest = query_result.receipt.projected_result_digest
    trusted_cutoff = query_result.receipt.observation_cutoff

    if (
        principal_ref != existing_result.request.requester_ref
        or correlation_ref != existing_result.request.correlation_ref
    ):
        reasons.add(ShadowComparisonReason.CONTEXT_REF_MISMATCH)
    try:
        lineage_matches = semantic_lineage_matches(
            query_result,
            semantic_receipt,
            profile=query_profile,
            plan=semantic_plan,
        )
    except Exception:  # noqa: BLE001 - malformed sealed input closes as ERROR
        lineage_matches = False
    if not lineage_matches:
        reasons.add(ShadowComparisonReason.SEMANTIC_LINEAGE_MISMATCH)

    existing = extract_existing_state(
        existing_result,
        trusted_cutoff=trusted_cutoff,
        identity_canonicalizer=identity_canonicalizer,
    )
    semantic = extract_semantic_state(
        query_result,
        trusted_cutoff=trusted_cutoff,
        identity_canonicalizer=identity_canonicalizer,
    )
    reasons.update(existing.reasons)
    reasons.update(semantic.reasons)

    blocking_outcome, selected_reasons = select_shadow_outcome(reasons)
    adjudicated: StateFactMetadata | None = None
    if blocking_outcome is not None:
        outcome = blocking_outcome
    else:
        baseline = existing.observation
        candidate = semantic.observation
        if baseline is None or candidate is None:  # pragma: no cover - extraction contract
            outcome = ShadowComparisonOutcome.ERROR
            selected_reasons = (ShadowComparisonReason.SEMANTIC_EVIDENCE_MALFORMED,)
        else:
            mismatch_reasons = observation_mismatches(baseline, candidate)
            outcome = (
                ShadowComparisonOutcome.DIVERGENCE
                if mismatch_reasons
                else ShadowComparisonOutcome.MATCH
            )
            selected_reasons = tuple(sorted(mismatch_reasons, key=str))
            existing_digest = baseline.evidence_digest
            semantic_digest = candidate.evidence_digest
            adjudicated = cross_source_state_fact(
                baseline,
                candidate,
                trusted_cutoff=trusted_cutoff,
            )

    receipt = build_shadow_receipt(
        outcome=outcome,
        reasons=selected_reasons,
        cross_source_conflicts=adjudicated.conflicts if adjudicated is not None else (),
        correlation_ref=correlation_ref,
        principal_ref=principal_ref,
        release_digest=semantic_receipt.ontology_release.digest,
        profile_digest=semantic_receipt.profile_digest,
        plan_digest=semantic_receipt.plan_digest,
        semantic_request_id=semantic_receipt.request_id,
        semantic_receipt_digest=semantic_receipt.receipt_digest,
        invocation_digest=semantic_invocation_digest,
        existing_evidence_digest=existing_digest,
        semantic_evidence_digest=semantic_digest,
    )
    return receipt, adjudicated, existing.observation, semantic.observation


def _evidence_lineage(
    observation: NormalizedResourceStateObservation,
) -> EvidenceSourceLineage:
    return EvidenceSourceLineage(
        source_identity=observation.source_identity,
        source_revision=observation.source_revision,
        claim_digest=observation.claim_digest,
        authority=observation.authority,
        evidence_cutoff=observation.evidence_cutoff,
        recorded_at=observation.recorded_at,
        freshness_ceiling_seconds=observation.freshness_ceiling_seconds,
        evidence_refs=observation.evidence_refs,
    )


def _failed_attempt(
    *,
    existing_result: ReadInvestigationResult,
    receipt: ShadowComparisonReceipt,
    correlation_ref: str,
    attempt_latency_ms: float | None,
    cross_source_state_fact: StateFactMetadata | None,
    error_kind: ShadowSinkErrorKind,
) -> ShadowComparisonAttempt:
    _LOG.warning(
        "resource_state_shadow_receipt_append_failed",
        extra={
            "correlation_id": correlation_ref,
            "error_kind": error_kind.value,
            "receipt_digest": receipt.receipt_digest,
        },
    )
    return ShadowComparisonAttempt(
        authoritative_result=existing_result,
        receipt=receipt,
        persistence=ShadowReceiptPersistence.FAILED,
        attempt_latency_ms=attempt_latency_ms,
        sink_error_kind=error_kind,
        cross_source_state_fact=cross_source_state_fact,
    )


__all__ = ["ShadowResourceStateComparisonService"]
