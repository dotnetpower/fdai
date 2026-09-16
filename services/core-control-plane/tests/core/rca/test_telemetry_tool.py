from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fdai.core.ontology_platform.query_execution import OntologyQueryPlanExecutor
from fdai.core.ontology_platform.query_manifest import QueryManifest
from fdai.core.ontology_platform.query_telemetry_handlers import (
    TELEMETRY_RECIPE_ARGUMENT_SCHEMA,
    TelemetryRecipeNodeHandler,
)
from fdai.core.ontology_platform.query_verification import OntologyQueryPlanVerifier
from fdai.core.rca import (
    DEFAULT_TELEMETRY_RECIPE_CATALOG,
    TelemetryEvidenceDisposition,
    build_telemetry_evidence_need,
    build_telemetry_evidence_receipt,
)
from fdai.core.rca.telemetry_evidence_codec import telemetry_evidence_need_to_mapping
from fdai.core.rca.telemetry_tool import TelemetryEvidenceRecipeTool
from fdai.shared.contracts.models import CeilingRole
from fdai_service_contracts.ontology_query import (
    EvidenceAuthority,
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    StructuralCoverageReceipt,
    canonical_json,
    content_digest,
)

_NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)
_RELEASE = f"sha256:{'a' * 64}"
_SCOPE = f"sha256:{'b' * 64}"


def _need():
    return build_telemetry_evidence_need(
        incident_id="incident:one",
        resource_ref="resource:one",
        evidence_cutoff=_NOW,
        recipe=DEFAULT_TELEMETRY_RECIPE_CATALOG.get("requests.failed", "1.0.0"),
        max_query_count=4,
        max_cost_units=100,
        idempotency_key="incident:one:round:one",
    )


class _Provider:
    def __init__(self) -> None:
        self.calls = 0

    async def gather(self, need):
        self.calls += 1
        await asyncio.sleep(0)
        return build_telemetry_evidence_receipt(
            need=need,
            observed_until=_NOW,
            disposition=TelemetryEvidenceDisposition.COMPLETE,
            route_count=1,
            queried_route_count=1,
            row_count=1,
            latency_ms=1,
            estimated_cost_units=10,
            actual_cost_units=10,
            fact_tokens=("mechanism:failed_requests", "signal_count_band:low"),
            complete=True,
            truncated=False,
        )


class _CancellableProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def gather(self, need):
        self.calls += 1
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


def _manifest() -> QueryManifest:
    manifest_digest = content_digest(
        {
            "release_digest": _RELEASE,
            "principal_role": "reader",
            "purposes": ("operations-review",),
            "descriptors": (),
            "unavailable": (),
            "mutation_authority": False,
        }
    )
    coverage = StructuralCoverageReceipt(
        ontology_release_digest=_RELEASE,
        principal_scope_digest=_SCOPE,
        readable_declaration_count=0,
        descriptor_count=0,
        unavailable_declaration_ids=(),
        manifest_digest=manifest_digest,
        complete=True,
        receipt_digest=content_digest(
            {
                "schema_version": "1.0.0",
                "ontology_release_digest": _RELEASE,
                "principal_scope_digest": _SCOPE,
                "readable_declaration_count": 0,
                "descriptor_count": 0,
                "unavailable_declaration_ids": (),
                "manifest_digest": manifest_digest,
                "complete": True,
            }
        ),
    )
    return QueryManifest(
        release_digest=_RELEASE,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        descriptors=(),
        unavailable=(),
        manifest_digest=manifest_digest,
        coverage_receipt=coverage,
    )


def _plan(arguments: dict[str, object]) -> OntologyQueryPlan:
    manifest = _manifest()
    node = OntologyQueryNode(
        node_id="telemetry",
        kind=QueryNodeKind.TELEMETRY_RECIPE,
        arguments_json=canonical_json(arguments),
        output_kind="telemetry.evidence",
    )
    material = {
        "schema_version": "1.0.0",
        "ontology_release_digest": _RELEASE,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": _SCOPE,
        "purpose": "operations-review",
        "caller_role": "reader",
        "nodes": [node.model_dump(mode="json")],
        "output_node_ids": ("telemetry",),
        "execution_authority": False,
    }
    return OntologyQueryPlan(
        ontology_release_digest=_RELEASE,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=_SCOPE,
        purpose="operations-review",
        caller_role="reader",
        nodes=(node,),
        output_node_ids=("telemetry",),
        plan_digest=content_digest(material),
    )


@pytest.mark.asyncio
async def test_tool_coalesces_concurrent_and_replayed_need() -> None:
    provider = _Provider()
    tool = TelemetryEvidenceRecipeTool(provider=provider)
    need = _need()

    first, second = await asyncio.gather(tool.run(need), tool.run(need))
    replay = await tool.run(need)

    assert first == second == replay
    assert provider.calls == 1
    assert tool.receipt(first.receipt_digest) == first


@pytest.mark.asyncio
async def test_tool_cancellation_stops_provider_work_and_removes_in_flight_entry() -> None:
    provider = _CancellableProvider()
    tool = TelemetryEvidenceRecipeTool(provider=provider)
    need = _need()
    run = asyncio.create_task(tool.run(need))
    await provider.started.wait()

    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    await provider.cancelled.wait()

    retry = asyncio.create_task(tool.run(need))
    for _ in range(10):
        if provider.calls == 2:
            break
        await asyncio.sleep(0)
    assert provider.calls == 2
    retry.cancel()
    with pytest.raises(asyncio.CancelledError):
        await retry


@pytest.mark.asyncio
async def test_verified_node_executes_typed_tool_and_carries_log_authority() -> None:
    provider = _Provider()
    tool = TelemetryEvidenceRecipeTool(provider=provider)
    manifest = _manifest()
    plan = _plan({"need": telemetry_evidence_need_to_mapping(_need())})
    verifier = OntologyQueryPlanVerifier(
        available_kinds=(QueryNodeKind.TELEMETRY_RECIPE,),
        extension_argument_schemas={
            QueryNodeKind.TELEMETRY_RECIPE: TELEMETRY_RECIPE_ARGUMENT_SCHEMA
        },
    )
    executor = OntologyQueryPlanExecutor(
        handlers={QueryNodeKind.TELEMETRY_RECIPE: TelemetryRecipeNodeHandler(tool)}
    )

    result = await executor.execute(
        verifier.verify(plan, manifest=manifest),
        expected_release_digest=_RELEASE,
        expected_manifest_digest=manifest.manifest_digest,
        expected_role="reader",
        expected_purpose="operations-review",
    )

    assert result.status == "completed"
    assert result.results["telemetry"].authority is EvidenceAuthority.SERVER_OPERATIONAL_LOGS
    assert result.receipts[0].evidence_refs[0].startswith("telemetry-receipt:sha256:")


@pytest.mark.asyncio
async def test_verifier_rejects_raw_query_fields_before_tool_execution() -> None:
    provider = _Provider()
    need = telemetry_evidence_need_to_mapping(_need())
    need["kql"] = "AppRequests | take 1"
    plan = _plan({"need": need})
    verifier = OntologyQueryPlanVerifier(
        available_kinds=(QueryNodeKind.TELEMETRY_RECIPE,),
        extension_argument_schemas={
            QueryNodeKind.TELEMETRY_RECIPE: TELEMETRY_RECIPE_ARGUMENT_SCHEMA
        },
    )

    with pytest.raises(ValueError, match="registered schema"):
        verifier.verify(plan, manifest=_manifest())

    assert provider.calls == 0
