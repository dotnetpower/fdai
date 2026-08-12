"""Round-9 lineage, completeness, and sink hardening regressions."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fdai.core.read_investigation.resource_state_shadow_models import (
    ShadowComparisonOutcome,
    ShadowComparisonReason,
    ShadowReceiptPersistence,
    ShadowSinkErrorKind,
)
from fdai.core.read_investigation.resource_state_shadow_service import (
    ShadowResourceStateComparisonService,
)
from fdai.core.read_investigation.shadow_sink import (
    InMemoryShadowComparisonSink,
    ShadowReceiptIdentityConflictError,
    ShadowSinkAppendResult,
    StateStoreShadowComparisonSink,
)
from fdai.shared.providers.read_investigation import EvidenceLimitationKind
from fdai.shared.providers.testing import InMemoryStateStore
from tests.core.read_investigation.test_resource_state_shadow import (
    NOW,
    RESOURCE_REF,
    _canonical_request_id,
    _compare,
    _existing_result,
    _reseal_semantic_receipt,
    _reviewed_lineage,
    _semantic_inputs,
)


async def test_sink_type_error_is_classified_as_append_failure() -> None:
    class _TypeErrorSink:
        async def append(self, receipt: object) -> ShadowSinkAppendResult:
            del receipt
            raise TypeError("backend serialization failed")

    query_result, semantic_receipt = _semantic_inputs()
    _, query_profile, semantic_plan = _reviewed_lineage(query_result.materialization.definition)
    attempt = await ShadowResourceStateComparisonService(sink=_TypeErrorSink()).compare(
        existing_result=_existing_result(),
        query_result=query_result,
        semantic_receipt=semantic_receipt,
        query_profile=query_profile,
        semantic_plan=semantic_plan,
        principal_ref="principal:reader",
        correlation_ref="correlation:one",
    )

    assert attempt.persistence is ShadowReceiptPersistence.FAILED
    assert attempt.sink_error_kind is ShadowSinkErrorKind.APPEND_FAILED


async def test_state_store_sink_records_and_retains_exact_replay() -> None:
    attempt, _ = await _compare()
    sink = StateStoreShadowComparisonSink(store=InMemoryStateStore())

    first = await sink.append(attempt.receipt)
    replay = await sink.append(attempt.receipt)

    assert first.persistence is ShadowReceiptPersistence.RECORDED
    assert replay.persistence is ShadowReceiptPersistence.RETAINED
    assert replay.receipt == attempt.receipt


async def test_state_store_sink_rejects_malformed_retained_state() -> None:
    attempt, _ = await _compare()
    store = InMemoryStateStore()
    await store.write_state(
        f"read-investigation-shadow:{attempt.receipt.receipt_digest}",
        {
            "record_type": "read_investigation.resource_state_shadow.v1",
            "receipt": {"outcome": "match"},
        },
    )

    with pytest.raises(
        ShadowReceiptIdentityConflictError,
        match="malformed retained content",
    ):
        await StateStoreShadowComparisonSink(store=store).append(attempt.receipt)


async def test_exact_reviewed_profile_is_required() -> None:
    query_result, semantic_receipt = _semantic_inputs()
    _, query_profile, semantic_plan = _reviewed_lineage(query_result.materialization.definition)
    forged_profile = query_profile.model_copy(update={"purpose": "other-purpose"})

    attempt, _ = await _compare(
        query_result=query_result,
        semantic_receipt=semantic_receipt,
        query_profile=forged_profile,
        semantic_plan=semantic_plan,
    )

    assert attempt.receipt.outcome is ShadowComparisonOutcome.ERROR
    assert attempt.receipt.reasons == (ShadowComparisonReason.SEMANTIC_LINEAGE_MISMATCH,)


async def test_verified_plan_digest_is_recomputed_not_merely_cross_compared() -> None:
    query_result, semantic_receipt = _semantic_inputs()
    _, query_profile, semantic_plan = _reviewed_lineage(query_result.materialization.definition)
    forged_digest = "sha256:" + "9" * 64
    forged_plan = semantic_plan.model_copy(update={"plan_digest": forged_digest})
    forged_request_id = _canonical_request_id(
        ontology_release=semantic_receipt.ontology_release,
        profile=query_profile,
        plan_digest=forged_digest,
        invocation=semantic_receipt.function_invocation,
    )
    forged_receipt = _reseal_semantic_receipt(
        semantic_receipt,
        request_id=forged_request_id,
        plan_digest=forged_digest,
    )

    attempt, _ = await _compare(
        query_result=query_result,
        semantic_receipt=forged_receipt,
        query_profile=query_profile,
        semantic_plan=forged_plan,
    )

    assert attempt.receipt.outcome is ShadowComparisonOutcome.ERROR
    assert attempt.receipt.reasons == (ShadowComparisonReason.SEMANTIC_LINEAGE_MISMATCH,)


async def test_noncanonical_semantic_request_id_is_rejected_when_resealed() -> None:
    query_result, semantic_receipt = _semantic_inputs()
    forged_receipt = _reseal_semantic_receipt(
        semantic_receipt,
        request_id="semantic-query-request:" + "2" * 64,
    )

    attempt, _ = await _compare(
        query_result=query_result,
        semantic_receipt=forged_receipt,
    )

    assert attempt.receipt.outcome is ShadowComparisonOutcome.ERROR
    assert attempt.receipt.reasons == (ShadowComparisonReason.SEMANTIC_LINEAGE_MISMATCH,)


async def test_graph_only_truncation_always_blocks_match() -> None:
    query_result, semantic_receipt = _semantic_inputs(graph_truncated=True)

    attempt, _ = await _compare(
        query_result=query_result,
        semantic_receipt=semantic_receipt,
    )

    assert attempt.receipt.outcome is ShadowComparisonOutcome.UNAVAILABLE
    assert attempt.receipt.reasons == (ShadowComparisonReason.SEMANTIC_RESULT_TRUNCATED,)


async def test_relevant_existing_limitation_blocks_match() -> None:
    existing = _existing_result(limitations=(EvidenceLimitationKind.SOURCE_CUTOFF,))

    attempt, _ = await _compare(existing=existing)

    assert attempt.receipt.outcome is ShadowComparisonOutcome.UNAVAILABLE
    assert attempt.receipt.reasons == (ShadowComparisonReason.EXISTING_EVIDENCE_UNAVAILABLE,)


async def test_semantic_redaction_blocks_match() -> None:
    query_result, semantic_receipt = _semantic_inputs(redacted_identity_count=1)

    attempt, _ = await _compare(
        query_result=query_result,
        semantic_receipt=semantic_receipt,
    )

    assert attempt.receipt.outcome is ShadowComparisonOutcome.UNAVAILABLE
    assert attempt.receipt.reasons == (ShadowComparisonReason.SEMANTIC_RESULT_UNAVAILABLE,)


async def test_existing_observation_uses_same_300_second_cutoff() -> None:
    existing = _existing_result(observed_at=NOW - timedelta(seconds=301))

    attempt, _ = await _compare(existing=existing)

    assert attempt.receipt.outcome is ShadowComparisonOutcome.UNAVAILABLE
    assert attempt.receipt.reasons == (ShadowComparisonReason.EXISTING_OBSERVATION_STALE,)


async def test_both_observations_match_at_exact_300_second_boundary() -> None:
    observed_at = NOW - timedelta(seconds=300)
    existing = _existing_result(observed_at=observed_at)
    query_result, semantic_receipt = _semantic_inputs(observed_at=observed_at)

    attempt, _ = await _compare(
        existing=existing,
        query_result=query_result,
        semantic_receipt=semantic_receipt,
    )

    assert attempt.receipt.outcome is ShadowComparisonOutcome.MATCH


async def test_opaque_resource_identity_is_exact_by_default() -> None:
    query_result, semantic_receipt = _semantic_inputs(resource_ref=RESOURCE_REF.upper())

    attempt, _ = await _compare(
        query_result=query_result,
        semantic_receipt=semantic_receipt,
    )

    assert attempt.receipt.outcome is ShadowComparisonOutcome.DIVERGENCE
    assert attempt.receipt.reasons == (ShadowComparisonReason.RESOURCE_IDENTITY_MISMATCH,)


async def test_injected_trusted_identity_canonicalizer_can_equate_resource_ids() -> None:
    query_result, semantic_receipt = _semantic_inputs(resource_ref=RESOURCE_REF.upper())

    attempt, _ = await _compare(
        query_result=query_result,
        semantic_receipt=semantic_receipt,
        identity_canonicalizer=str.casefold,
    )

    assert attempt.receipt.outcome is ShadowComparisonOutcome.MATCH


async def test_canonicalizer_failure_becomes_deterministic_error_receipt() -> None:
    def _fail_canonicalization(_value: str) -> str:
        raise RuntimeError("canonicalizer unavailable")

    attempt, _ = await _compare(identity_canonicalizer=_fail_canonicalization)

    assert attempt.receipt.outcome is ShadowComparisonOutcome.ERROR
    assert attempt.receipt.reasons == (
        ShadowComparisonReason.EXISTING_EVIDENCE_MALFORMED,
        ShadowComparisonReason.SEMANTIC_EVIDENCE_MALFORMED,
    )


async def test_oversized_semantic_properties_are_rejected_before_shadow_hashing() -> None:
    query_result, semantic_receipt = _semantic_inputs(extra_properties={"padding": "x" * 40_000})

    attempt, _ = await _compare(
        query_result=query_result,
        semantic_receipt=semantic_receipt,
    )

    assert attempt.receipt.outcome is ShadowComparisonOutcome.ERROR
    assert ShadowComparisonReason.SEMANTIC_LINEAGE_MISMATCH in attempt.receipt.reasons
    assert ShadowComparisonReason.SEMANTIC_EVIDENCE_MALFORMED in attempt.receipt.reasons


async def test_oversized_invocation_evidence_is_rejected_before_shadow_hashing() -> None:
    query_result, semantic_receipt = _semantic_inputs()
    oversized_invocation = semantic_receipt.function_invocation.model_copy(
        update={"evidence_refs": tuple(f"evidence:{index}" for index in range(65))}
    )
    forged_receipt = _reseal_semantic_receipt(
        semantic_receipt,
        invocation=oversized_invocation,
    )

    attempt, _ = await _compare(
        query_result=query_result,
        semantic_receipt=forged_receipt,
    )

    assert attempt.receipt.outcome is ShadowComparisonOutcome.ERROR
    assert attempt.receipt.reasons == (ShadowComparisonReason.SEMANTIC_LINEAGE_MISMATCH,)


async def test_shadow_identity_includes_semantic_request_and_receipt_digests() -> None:
    _, semantic_receipt = _semantic_inputs()

    attempt, _ = await _compare(semantic_receipt=semantic_receipt)

    assert attempt.receipt.semantic_request_id == semantic_receipt.request_id
    assert attempt.receipt.semantic_receipt_digest == semantic_receipt.receipt_digest


async def test_duplicate_sink_returns_retained_receipt_and_attempt_latency() -> None:
    sink = InMemoryShadowComparisonSink()
    first, _ = await _compare(sink=sink, latency_ms=1.0)
    replay, _ = await _compare(sink=sink, latency_ms=2.0)

    assert first.persistence is ShadowReceiptPersistence.RECORDED
    assert replay.persistence is ShadowReceiptPersistence.RETAINED
    assert replay.receipt is (await sink.list_receipts())[0]
    assert replay.attempt_latency_ms == 2.0


async def test_sink_rejects_conflicting_content_for_same_identity() -> None:
    sink = InMemoryShadowComparisonSink()
    attempt, _ = await _compare(sink=sink)
    conflicting = attempt.receipt.model_copy(update={"principal_ref": "principal:other"})

    with pytest.raises(ShadowReceiptIdentityConflictError):
        await sink.append(conflicting)


async def test_service_observes_conflicting_record_without_response_impact() -> None:
    class _ConflictingSink:
        async def append(self, receipt: Any) -> ShadowSinkAppendResult:
            conflicting = receipt.model_copy(update={"principal_ref": "principal:other"})
            return ShadowSinkAppendResult(
                receipt=conflicting,
                persistence=ShadowReceiptPersistence.RETAINED,
            )

    existing = _existing_result()
    query_result, semantic_receipt = _semantic_inputs()
    _, query_profile, semantic_plan = _reviewed_lineage(query_result.materialization.definition)
    attempt = await ShadowResourceStateComparisonService(sink=_ConflictingSink()).compare(
        existing_result=existing,
        query_result=query_result,
        semantic_receipt=semantic_receipt,
        query_profile=query_profile,
        semantic_plan=semantic_plan,
        principal_ref="principal:reader",
        correlation_ref="correlation:one",
    )

    assert attempt.authoritative_result is existing
    assert attempt.persistence is ShadowReceiptPersistence.FAILED
    assert attempt.sink_error_kind is ShadowSinkErrorKind.IDENTITY_CONFLICT
