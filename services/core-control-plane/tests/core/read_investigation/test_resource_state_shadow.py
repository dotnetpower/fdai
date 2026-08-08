"""Focused tests for read-only resource-state shadow comparisons."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.core.ontology_platform.functions import (
    FunctionInvocationReceipt,
    ontology_function_digest,
)
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
    ObjectSetTruncationReason,
)
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
)
from fdai.core.ontology_platform.semantic_query import SemanticQueryReceipt
from fdai.core.read_investigation.models import (
    ReadInvestigationBudget,
    ReadInvestigationOutcome,
    ReadInvestigationRequest,
    ReadInvestigationResult,
)
from fdai.core.read_investigation.resource_state_shadow_models import (
    ShadowComparisonOutcome,
    ShadowComparisonReason,
    ShadowReceiptPersistence,
)
from fdai.core.read_investigation.resource_state_shadow_service import (
    ShadowResourceStateComparisonService,
)
from fdai.core.read_investigation.shadow_sink import InMemoryShadowComparisonSink
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyDeclarationKind,
    OntologyReleaseRef,
    OntologyTypeRef,
)
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyObjectRecord,
)
from fdai.shared.providers.read_investigation import (
    EvidenceFreshness,
    EvidenceLimitationKind,
    EvidenceStatus,
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ReadInvestigationIntent,
    ResolvedResource,
    ResourceResolution,
    ResourceResolutionStatus,
    ResourceSelector,
)
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

NOW = datetime(2026, 8, 8, 12, tzinfo=UTC)
RESOURCE_REF = "resource:example-vm"
RELEASE_DIGEST = "sha256:" + "a" * 64
PROFILE_DIGEST = "sha256:" + "b" * 64
PLAN_DIGEST = "sha256:" + "c" * 64


def _request() -> ReadInvestigationRequest:
    return ReadInvestigationRequest(
        requester_ref="principal:reader",
        conversation_ref="conversation:one",
        correlation_ref="correlation:one",
        intent=ReadInvestigationIntent.RESOURCE_STATE,
        selector=ResourceSelector(name="vm-example", scope_ref="scope:allowed"),
        lookback_seconds=3_600,
        requested_evidence=(),
        budget=ReadInvestigationBudget(),
        idempotency_key="request:one",
        created_at=NOW,
    )


def _existing_result(
    *,
    state: str = "running",
    observed_at: datetime = NOW,
    resource_ref: str = RESOURCE_REF,
    outcome: ReadInvestigationOutcome = ReadInvestigationOutcome.MATCHED,
    freshness: EvidenceFreshness = EvidenceFreshness.LIVE,
    truncated: bool = False,
) -> ReadInvestigationResult:
    evidence_status = (
        EvidenceStatus.MATCHED
        if outcome is ReadInvestigationOutcome.MATCHED
        else EvidenceStatus.UNAVAILABLE
    )
    records = (
        (ReadEvidenceRecord(occurred_at=observed_at, status="ok", state=state),)
        if evidence_status is EvidenceStatus.MATCHED
        else ()
    )
    truncation_reason = EvidenceLimitationKind.RESULT_LIMIT if truncated else None
    return ReadInvestigationResult(
        request=_request(),
        outcome=outcome,
        resolution=ResourceResolution(
            status=ResourceResolutionStatus.MATCHED,
            resource=ResolvedResource(
                resource_ref=resource_ref,
                scope_ref="scope:allowed",
                name="vm-example",
                resource_type="compute.vm",
            ),
        ),
        evidence=(
            ReadEvidenceEnvelope(
                status=evidence_status,
                authority="azure.resource_state",
                resource_ref=resource_ref,
                observed_at=observed_at,
                freshness=freshness,
                truncated=truncated,
                records=records,
                evidence_refs=("evidence:read-state",) if records else (),
                limitations=((truncation_reason,) if truncation_reason is not None else ()),
                truncation_reason=truncation_reason,
            ),
        ),
        receipts=(),
        progress_kinds=("investigation.completed",),
        started_at=NOW - timedelta(milliseconds=5),
        finished_at=NOW,
    )


def _state_metadata(
    *,
    observed_at: datetime,
    freshness_ceiling_seconds: int = 300,
) -> StateFactMetadata:
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision="revision-7",
        effective_at=observed_at,
        recorded_at=NOW,
        evidence_cutoff=observed_at,
        freshness_ceiling_seconds=freshness_ceiling_seconds,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("evidence:ontology-state",),
    )


def _projected_result_digest(materialization: ObjectSetMaterialization) -> str:
    graph = materialization.graph
    return ontology_function_digest(
        {
            "definition": materialization.definition.model_dump(mode="json"),
            "objects": [
                {
                    "id": item.id,
                    "object_type": item.object_type,
                    "properties": dict(item.properties),
                    "revision": item.revision,
                    "type_ref": (
                        item.type_ref.model_dump(mode="json") if item.type_ref is not None else None
                    ),
                }
                for item in graph.objects
            ],
            "links": [],
            "graph_truncated": graph.truncated,
            "concrete_types": list(materialization.concrete_types),
            "truncated": materialization.truncated,
            "truncation_reason": (
                materialization.truncation_reason.value
                if materialization.truncation_reason is not None
                else None
            ),
        }
    )


def _semantic_inputs(
    *,
    state: str = "running",
    observed_at: datetime = NOW,
    resource_ref: str = RESOURCE_REF,
    truncated: bool = False,
    freshness_ceiling_seconds: int = 300,
) -> tuple[SecuredObjectSetQueryResult, SemanticQueryReceipt]:
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="resource-state-shadow",
        limit=1,
    )
    state_fact = _state_metadata(
        observed_at=observed_at,
        freshness_ceiling_seconds=freshness_ceiling_seconds,
    )
    graph = OntologyGraphSnapshot(
        objects=(
            OntologyObjectRecord(
                id=resource_ref,
                object_type="Resource",
                properties={
                    "id": resource_ref,
                    "type": "compute.vm",
                    "properties": {
                        "state": state,
                        STATE_FACT_METADATA_PROPERTY: state_fact.to_mapping(),
                    },
                },
            ),
        ),
        truncated=truncated,
    )
    truncation_reason = ObjectSetTruncationReason.RESULT_LIMIT if truncated else None
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=graph,
        concrete_types=("Resource",),
        truncated=truncated,
        truncation_reason=truncation_reason,
    )
    release = OntologyReleaseRef(digest=RELEASE_DIGEST)
    query_receipt = SecuredObjectSetQueryReceipt(
        ontology_release=release,
        projected_result_digest=_projected_result_digest(materialization),
        purpose=definition.purpose,
        caller_role=CeilingRole.READER,
        observation_cutoff=NOW,
        as_of_skew_seconds=0,
        returned_object_count=1,
        returned_link_count=0,
        complete=not truncated,
        truncated=truncated,
        truncation_reason=truncation_reason,
        redactions=ObjectSetRedactionSummary(
            objects_with_redactions=0,
            redacted_identity_count=0,
            access_scope_count=0,
            purpose_binding_count=0,
            undeclared_property_count=0,
            links_with_redactions=0,
            redacted_link_property_count=0,
            removed_link_count=0,
        ),
    )
    query_result = SecuredObjectSetQueryResult(
        materialization=materialization,
        receipt=query_receipt,
    )
    function_ref = OntologyTypeRef(
        kind=OntologyDeclarationKind.FUNCTION,
        name="inventory.select_resources",
        version="1.0.0",
        catalog_digest=RELEASE_DIGEST,
    )
    invocation = FunctionInvocationReceipt(
        request_id="logic-request:" + "d" * 64,
        invocation_id="logic-invocation:" + "e" * 64,
        function_ref=function_ref,
        caller_agent="Bragi",
        caller_role=CeilingRole.READER,
        purposes=(definition.purpose,),
        input_digest="sha256:" + "f" * 64,
        output_digest=ontology_function_digest(query_result.model_dump(mode="json")),
        started_at=NOW - timedelta(milliseconds=2),
        completed_at=NOW - timedelta(milliseconds=1),
        evidence_refs=("evidence:ontology-state",),
    )
    semantic_digest = ontology_function_digest(
        {
            "ontology_release": release.model_dump(mode="json"),
            "profile_ref": "query-profile:resource-state@1.0.0",
            "profile_digest": PROFILE_DIGEST,
            "request_id": "semantic-query-request:" + "1" * 64,
            "plan_digest": PLAN_DIGEST,
            "function_invocation": invocation.model_dump(mode="json"),
            "truncated": truncated,
            "truncation_reason": (
                truncation_reason.value if truncation_reason is not None else None
            ),
            "execution_authority": False,
        }
    )
    semantic_receipt = SemanticQueryReceipt(
        ontology_release=release,
        profile_ref="query-profile:resource-state@1.0.0",
        profile_digest=PROFILE_DIGEST,
        request_id="semantic-query-request:" + "1" * 64,
        plan_digest=PLAN_DIGEST,
        function_invocation=invocation,
        truncated=truncated,
        truncation_reason=truncation_reason,
        receipt_digest=semantic_digest,
    )
    return query_result, semantic_receipt


async def _compare(
    *,
    existing: ReadInvestigationResult | None = None,
    query_result: SecuredObjectSetQueryResult | None = None,
    semantic_receipt: SemanticQueryReceipt | None = None,
    sink: InMemoryShadowComparisonSink | None = None,
    latency_ms: float | None = 4.5,
) -> tuple[Any, InMemoryShadowComparisonSink]:
    actual_sink = sink or InMemoryShadowComparisonSink()
    if query_result is None or semantic_receipt is None:
        query_result, semantic_receipt = _semantic_inputs()
    attempt = await ShadowResourceStateComparisonService(sink=actual_sink).compare(
        existing_result=existing or _existing_result(),
        query_result=query_result,
        semantic_receipt=semantic_receipt,
        principal_ref="principal:reader",
        correlation_ref="correlation:one",
        attempt_latency_ms=latency_ms,
    )
    return attempt, actual_sink


async def test_exact_resource_state_match_is_recorded() -> None:
    attempt, sink = await _compare()

    assert attempt.receipt.outcome is ShadowComparisonOutcome.MATCH
    assert attempt.receipt.reasons == ()
    assert attempt.persistence is ShadowReceiptPersistence.RECORDED
    assert await sink.list_receipts() == (attempt.receipt,)


async def test_state_divergence_is_observed_without_changing_authority() -> None:
    query_result, semantic_receipt = _semantic_inputs(state="stopped")

    attempt, _ = await _compare(
        query_result=query_result,
        semantic_receipt=semantic_receipt,
    )

    assert attempt.receipt.outcome is ShadowComparisonOutcome.DIVERGENCE
    assert attempt.receipt.reasons == (ShadowComparisonReason.STATE_MISMATCH,)
    assert attempt.authoritative_result.outcome is ReadInvestigationOutcome.MATCHED


async def test_existing_unavailable_result_stays_unavailable() -> None:
    existing = _existing_result(outcome=ReadInvestigationOutcome.UNAVAILABLE)

    attempt, _ = await _compare(existing=existing)

    assert attempt.receipt.outcome is ShadowComparisonOutcome.UNAVAILABLE
    assert ShadowComparisonReason.EXISTING_EVIDENCE_UNAVAILABLE in attempt.receipt.reasons
    assert attempt.authoritative_result is existing


async def test_resource_identity_mismatch_is_divergence() -> None:
    query_result, semantic_receipt = _semantic_inputs(resource_ref="resource:other-vm")

    attempt, _ = await _compare(
        query_result=query_result,
        semantic_receipt=semantic_receipt,
    )

    assert attempt.receipt.outcome is ShadowComparisonOutcome.DIVERGENCE
    assert ShadowComparisonReason.RESOURCE_IDENTITY_MISMATCH in attempt.receipt.reasons


async def test_truncated_semantic_result_cannot_match() -> None:
    query_result, semantic_receipt = _semantic_inputs(truncated=True)

    attempt, _ = await _compare(
        query_result=query_result,
        semantic_receipt=semantic_receipt,
    )

    assert attempt.receipt.outcome is ShadowComparisonOutcome.UNAVAILABLE
    assert ShadowComparisonReason.SEMANTIC_RESULT_TRUNCATED in attempt.receipt.reasons


async def test_stale_semantic_observation_cannot_match() -> None:
    query_result, semantic_receipt = _semantic_inputs(
        observed_at=NOW - timedelta(seconds=301),
        freshness_ceiling_seconds=300,
    )

    attempt, _ = await _compare(
        query_result=query_result,
        semantic_receipt=semantic_receipt,
    )

    assert attempt.receipt.outcome is ShadowComparisonOutcome.UNAVAILABLE
    assert ShadowComparisonReason.SEMANTIC_OBSERVATION_STALE in attempt.receipt.reasons


async def test_observation_time_mismatch_is_divergence() -> None:
    query_result, semantic_receipt = _semantic_inputs(observed_at=NOW - timedelta(seconds=1))

    attempt, _ = await _compare(
        query_result=query_result,
        semantic_receipt=semantic_receipt,
    )

    assert attempt.receipt.outcome is ShadowComparisonOutcome.DIVERGENCE
    assert ShadowComparisonReason.OBSERVED_AT_MISMATCH in attempt.receipt.reasons


async def test_receipt_identity_excludes_attempt_latency() -> None:
    fast, _ = await _compare(latency_ms=1.0)
    slow, _ = await _compare(latency_ms=999.0)

    assert fast.receipt.attempt_latency_ms == 1.0
    assert slow.receipt.attempt_latency_ms == 999.0
    assert fast.receipt.receipt_digest == slow.receipt.receipt_digest
    assert fast.receipt.model_dump(exclude={"attempt_latency_ms"}) == slow.receipt.model_dump(
        exclude={"attempt_latency_ms"}
    )


async def test_sink_failure_preserves_existing_response_and_is_observable() -> None:
    class _FailingSink:
        async def append(self, receipt: object) -> None:
            del receipt
            raise RuntimeError("durable sink unavailable")

    existing = _existing_result()
    query_result, semantic_receipt = _semantic_inputs()
    attempt = await ShadowResourceStateComparisonService(sink=_FailingSink()).compare(
        existing_result=existing,
        query_result=query_result,
        semantic_receipt=semantic_receipt,
        principal_ref="principal:reader",
        correlation_ref="correlation:one",
    )

    assert attempt.authoritative_result is existing
    assert attempt.receipt.outcome is ShadowComparisonOutcome.MATCH
    assert attempt.persistence is ShadowReceiptPersistence.FAILED
    assert attempt.sink_error_kind == "RuntimeError"


async def test_comparison_has_no_mutation_or_execution_authority() -> None:
    existing = _existing_result()
    query_result, semantic_receipt = _semantic_inputs()
    existing_before = existing
    query_before = query_result.model_dump(mode="json")

    attempt, _ = await _compare(
        existing=existing,
        query_result=query_result,
        semantic_receipt=semantic_receipt,
    )

    assert attempt.authoritative_result is existing_before
    assert existing == existing_before
    assert query_result.model_dump(mode="json") == query_before
    assert attempt.receipt.authority == "shadow_read_only"
    assert attempt.receipt.execution_authority is False


async def test_mismatched_semantic_lineage_emits_error_receipt() -> None:
    query_result, semantic_receipt = _semantic_inputs()
    mismatched_invocation = semantic_receipt.function_invocation.model_copy(
        update={"output_digest": "sha256:" + "9" * 64}
    )
    mismatched_receipt = semantic_receipt.model_copy(
        update={"function_invocation": mismatched_invocation}
    )

    attempt, _ = await _compare(
        query_result=query_result,
        semantic_receipt=mismatched_receipt,
    )

    assert attempt.receipt.outcome is ShadowComparisonOutcome.ERROR
    assert attempt.receipt.reasons == (ShadowComparisonReason.SEMANTIC_LINEAGE_MISMATCH,)
