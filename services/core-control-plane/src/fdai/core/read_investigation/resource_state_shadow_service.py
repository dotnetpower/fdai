"""Read-only orchestration for exact resource-state shadow comparisons.

The existing :class:`ReadInvestigationResult` remains the sole response
authority. This service only compares it with a separately verified semantic
query and emits a non-authoritative observation receipt.
"""

from __future__ import annotations

import logging

from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.core.ontology_platform.semantic_query import SemanticQueryReceipt
from fdai.core.read_investigation.models import ReadInvestigationResult
from fdai.core.read_investigation.resource_state_shadow_evidence import (
    existing_input_digest,
    extract_existing_state,
    extract_semantic_state,
    invocation_digest,
    observation_mismatches,
    semantic_lineage_matches,
)
from fdai.core.read_investigation.resource_state_shadow_models import (
    ShadowComparisonAttempt,
    ShadowComparisonOutcome,
    ShadowComparisonReason,
    ShadowComparisonReceipt,
    ShadowReceiptPersistence,
    build_shadow_receipt,
    select_shadow_outcome,
)
from fdai.core.read_investigation.shadow_sink import ShadowComparisonSink

_LOG = logging.getLogger(__name__)


class ShadowResourceStateComparisonService:
    """Compare two read-only state observations and append a shadow receipt.

    Sink failure is returned as attempt metadata and never changes, retries, or
    replaces the existing investigation result.
    """

    def __init__(self, *, sink: ShadowComparisonSink) -> None:
        self._sink = sink

    async def compare(
        self,
        *,
        existing_result: ReadInvestigationResult,
        query_result: SecuredObjectSetQueryResult,
        semantic_receipt: SemanticQueryReceipt,
        principal_ref: str,
        correlation_ref: str,
        attempt_latency_ms: float | None = None,
    ) -> ShadowComparisonAttempt:
        """Record a comparison while preserving the original response object."""

        receipt = _compare_receipt(
            existing_result=existing_result,
            query_result=query_result,
            semantic_receipt=semantic_receipt,
            principal_ref=principal_ref,
            correlation_ref=correlation_ref,
            attempt_latency_ms=attempt_latency_ms,
        )
        try:
            await self._sink.append(receipt)
        except Exception as exc:  # noqa: BLE001 - shadow persistence cannot rewrite response
            error_kind = type(exc).__name__
            _LOG.warning(
                "resource_state_shadow_receipt_append_failed",
                extra={
                    "correlation_id": correlation_ref,
                    "error_kind": error_kind,
                    "receipt_digest": receipt.receipt_digest,
                },
            )
            return ShadowComparisonAttempt(
                authoritative_result=existing_result,
                receipt=receipt,
                persistence=ShadowReceiptPersistence.FAILED,
                sink_error_kind=error_kind,
            )
        return ShadowComparisonAttempt(
            authoritative_result=existing_result,
            receipt=receipt,
            persistence=ShadowReceiptPersistence.RECORDED,
        )


def _compare_receipt(
    *,
    existing_result: ReadInvestigationResult,
    query_result: SecuredObjectSetQueryResult,
    semantic_receipt: SemanticQueryReceipt,
    principal_ref: str,
    correlation_ref: str,
    attempt_latency_ms: float | None,
) -> ShadowComparisonReceipt:
    existing_digest = existing_input_digest(existing_result)
    semantic_digest = query_result.receipt.projected_result_digest
    reasons: set[ShadowComparisonReason] = set()

    if (
        principal_ref != existing_result.request.requester_ref
        or correlation_ref != existing_result.request.correlation_ref
    ):
        reasons.add(ShadowComparisonReason.CONTEXT_REF_MISMATCH)
    if not semantic_lineage_matches(query_result, semantic_receipt):
        reasons.add(ShadowComparisonReason.SEMANTIC_LINEAGE_MISMATCH)

    existing = extract_existing_state(existing_result)
    semantic = extract_semantic_state(query_result)
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
        invocation_digest=invocation_digest(semantic_receipt),
        existing_evidence_digest=existing_digest,
        semantic_evidence_digest=semantic_digest,
        attempt_latency_ms=attempt_latency_ms,
    )


__all__ = ["ShadowResourceStateComparisonService"]
