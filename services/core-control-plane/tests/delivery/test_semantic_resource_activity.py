"""Exact-target semantic resource activity function tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
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
    _projected_result_digest,
)
from fdai.core.ontology_platform.resource_activity_queries import (
    RESOURCE_ACTIVITY_FUNCTION_NAME,
    resource_activity_function_type,
)
from fdai.delivery.semantic_resource_activity import semantic_resource_activity_function
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyObjectRecord
from fdai.shared.providers.read_investigation import (
    ActorKind,
    EvidenceFreshness,
    EvidenceStatus,
    ReadEvidenceAttempt,
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ReadToolId,
    ReadToolLimits,
    ResolvedResource,
    ResourceResolution,
    ResourceResolutionAttempt,
    ResourceResolutionStatus,
    ResourceSelector,
)
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallReceipt

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


class _Provider:
    transport = "test"

    def __init__(self) -> None:
        self.calls: list[ReadToolId] = []

    async def resolve_resource(
        self,
        selector: ResourceSelector,
        *,
        limits: ReadToolLimits,
    ) -> ResourceResolutionAttempt:
        del limits
        self.calls.append(ReadToolId.RESOLVE_RESOURCE)
        assert selector.name == "service-example-api"
        assert selector.resource_group == "example-rg"
        resource = ResolvedResource(
            resource_ref="scope-example/resource-group/example-rg/service-example-api",
            scope_ref=selector.scope_ref,
            name=selector.name,
            resource_type="container-app",
            resource_group=selector.resource_group,
        )
        return ResourceResolutionAttempt(
            ResourceResolution(ResourceResolutionStatus.MATCHED, resource=resource),
            _receipt(ReadToolId.RESOLVE_RESOURCE, "resource_resolution"),
        )

    async def query_resource_activity(
        self,
        resource: ResolvedResource,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        del limits
        self.calls.append(ReadToolId.QUERY_RESOURCE_ACTIVITY)
        assert resource.name == "service-example-api"
        assert lookback_seconds == 3600
        record = ReadEvidenceRecord(
            occurred_at=NOW,
            status="succeeded",
            operation_kind="microsoft_app_containerapps_write",
            actor_ref="principal-example",
            actor_kind=ActorKind.SERVICE_PRINCIPAL,
            correlation_ref="correlation-example",
        )
        return ReadEvidenceAttempt(
            tool_id=ReadToolId.QUERY_RESOURCE_ACTIVITY,
            evidence=ReadEvidenceEnvelope(
                status=EvidenceStatus.MATCHED,
                authority="azure.activity_log",
                resource_ref=resource.resource_ref,
                observed_at=NOW,
                freshness=EvidenceFreshness.LIVE,
                truncated=False,
                records=(record,),
                evidence_refs=("azure-activity:evidence-example",),
            ),
            receipt=_receipt(ReadToolId.QUERY_RESOURCE_ACTIVITY, "control_plane_activity"),
        )

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"unexpected provider call: {name}")


def _receipt(tool_id: ReadToolId, operation_class: str) -> ToolCallReceipt:
    return ToolCallReceipt(
        outcome=ToolCallOutcome.SUCCEEDED,
        receipt_ref=f"receipt:{tool_id.value}",
        tool_id=tool_id.value,
        transport="test",
        operation_class=operation_class,
        execution_duration_ms=1,
        recorded_at=NOW,
    )


def _query_result(*, complete: bool = True) -> SecuredObjectSetQueryResult:
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=10,
    )
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(
            objects=(
                OntologyObjectRecord(
                    id=(
                        "/subscriptions/scope-example/resourceGroups/example-rg/providers/"
                        "Microsoft.App/containerApps/service-example-api"
                    ),
                    object_type="Resource",
                    properties={
                        "id": "resource-example",
                        "name": "service-example-api",
                        "resource_group": "example-rg",
                    },
                ),
            ),
            links=(),
            truncated=not complete,
        ),
        concrete_types=("Resource",),
        truncated=not complete,
        truncation_reason=(None if complete else ObjectSetTruncationReason.RESULT_LIMIT),
    )
    release = build_ontology_release(function_types=(resource_activity_function_type(),))
    return SecuredObjectSetQueryResult(
        materialization=materialization,
        receipt=SecuredObjectSetQueryReceipt(
            ontology_release=release.ref(),
            projected_result_digest=_projected_result_digest(materialization),
            purpose="operations-review",
            caller_role="reader",
            observation_cutoff=NOW,
            as_of_skew_seconds=0,
            returned_object_count=1,
            returned_link_count=0,
            complete=complete,
            truncated=not complete,
            truncation_reason=(None if complete else ObjectSetTruncationReason.RESULT_LIMIT),
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
        ),
    )


def _context() -> FunctionInvocationContext:
    return FunctionInvocationContext(
        caller_agent="Bragi",
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
    )


async def test_semantic_activity_runs_exact_resolution_and_activity_steps() -> None:
    provider = _Provider()
    declaration = resource_activity_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        semantic_resource_activity_function(release, provider=provider),  # type: ignore[arg-type]
    )

    result = await registry.invoke(
        RESOURCE_ACTIVITY_FUNCTION_NAME,
        {
            "query_result": _query_result().model_dump(mode="json"),
            "lookback_seconds": 3600,
        },
        context=_context(),
    )

    assert isinstance(result, dict)
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE, ReadToolId.QUERY_RESOURCE_ACTIVITY]
    assert result["complete"] is True
    rows = result["rows"]
    assert isinstance(rows, list)
    values = rows[0]["values"]
    assert values["operation"] == "microsoft_app_containerapps_write"
    assert values["execution_authority"] is False


async def test_semantic_activity_rejects_incomplete_target_before_provider_io() -> None:
    provider = _Provider()
    declaration = resource_activity_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        semantic_resource_activity_function(release, provider=provider),  # type: ignore[arg-type]
    )

    result = await registry.invoke(
        RESOURCE_ACTIVITY_FUNCTION_NAME,
        {
            "query_result": _query_result(complete=False).model_dump(mode="json"),
            "lookback_seconds": 3600,
        },
        context=_context(),
    )

    assert isinstance(result, dict)
    assert provider.calls == []
    assert result["complete"] is False
    assert result["truncation_reason"] == "target_resolution_incomplete"
