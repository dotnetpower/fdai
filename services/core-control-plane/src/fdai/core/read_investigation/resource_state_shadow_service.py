"""Read-only orchestration for exact resource-state shadow comparisons.

The existing :class:`ReadInvestigationResult` remains the sole response
authority. This service only compares it with a separately verified semantic
query and emits a non-authoritative observation receipt.
"""

from __future__ import annotations

import logging

from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.core.ontology_platform.query_profiles import QueryProfile
from fdai.core.ontology_platform.semantic_plans import VerifiedSemanticPlan
from fdai.core.ontology_platform.semantic_query import SemanticQueryReceipt
from fdai.core.read_investigation.models import ReadInvestigationResult
from fdai.core.read_investigation.resource_state_shadow_evidence import (
    ResourceIdentityCanonicalizer,
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
    ) -> None:
        self._sink = sink
        self._identity_canonicalizer = identity_canonicalizer

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

        receipt = _compare_receipt(
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
                error_kind=ShadowSinkErrorKind.IDENTITY_CONFLICT,
            )
        except Exception as exc:  # noqa: BLE001 - shadow persistence cannot rewrite response
            del exc
            return _failed_attempt(
                existing_result=existing_result,
                receipt=receipt,
                correlation_ref=correlation_ref,
                attempt_latency_ms=attempt_latency_ms,
                error_kind=ShadowSinkErrorKind.APPEND_FAILED,
            )
        if not isinstance(append_result, ShadowSinkAppendResult):
            return _failed_attempt(
                existing_result=existing_result,
                receipt=receipt,
                correlation_ref=correlation_ref,
                attempt_latency_ms=attempt_latency_ms,
                error_kind=ShadowSinkErrorKind.INVALID_RESULT,
            )
        if append_result.receipt != receipt:
            return _failed_attempt(
                existing_result=existing_result,
                receipt=receipt,
                correlation_ref=correlation_ref,
                attempt_latency_ms=attempt_latency_ms,
                error_kind=ShadowSinkErrorKind.IDENTITY_CONFLICT,
            )
        return ShadowComparisonAttempt(
            authoritative_result=existing_result,
            receipt=append_result.receipt,
            persistence=append_result.persistence,
            attempt_latency_ms=attempt_latency_ms,
        )


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
) -> ShadowComparisonReceipt:
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

    return build_shadow_receipt(
        outcome=outcome,
        reasons=selected_reasons,
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


def _failed_attempt(
    *,
    existing_result: ReadInvestigationResult,
    receipt: ShadowComparisonReceipt,
    correlation_ref: str,
    attempt_latency_ms: float | None,
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
    )


__all__ = ["ShadowResourceStateComparisonService"]
