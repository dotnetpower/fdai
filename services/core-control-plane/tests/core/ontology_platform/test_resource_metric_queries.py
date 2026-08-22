"""Verified Resource metric collection FunctionType tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.detection.series import MetricSample
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.metric_semantics import (
    MetricAggregation,
    MetricSemanticDefinition,
    MetricSemanticRegistry,
    MetricWindow,
)
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
)
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
from fdai.core.ontology_platform.resource_metric_queries import (
    RESOURCE_METRIC_FUNCTION_NAME,
    resource_metric_function_type,
    resource_metric_inventory_function,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyObjectRecord

NOW = datetime(2026, 8, 21, 16, 0, tzinfo=UTC)
DEFINITION = MetricSemanticDefinition(
    concept_id="resource.saturation",
    provider_metric="container_app_cpu_nanocores",
    canonical_unit="nanocores",
    aggregation=MetricAggregation.AVERAGE,
    description="CPU consumption of the bounded runtime resource.",
)
REGISTRY = MetricSemanticRegistry.build((DEFINITION,))


def _resource(index: int) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=f"resource-{index:02d}",
        object_type="Resource",
        properties={
            "id": f"resource-{index:02d}",
            "name": f"service-{index:02d}",
            "type": "container-app",
        },
    )


def _query_result(count: int) -> SecuredObjectSetQueryResult:
    declaration = resource_metric_function_type()
    release = build_ontology_release(function_types=(declaration,))
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=1000,
    )
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(
            objects=tuple(_resource(index) for index in range(count)),
            links=(),
            truncated=False,
        ),
        concrete_types=("Resource",),
        truncated=False,
    )
    return SecuredObjectSetQueryResult(
        materialization=materialization,
        receipt=SecuredObjectSetQueryReceipt(
            ontology_release=release.ref(),
            projected_result_digest=_projected_result_digest(materialization),
            purpose="operations-review",
            caller_role="reader",
            observation_cutoff=NOW,
            as_of_skew_seconds=0,
            returned_object_count=count,
            returned_link_count=0,
            complete=True,
            truncated=False,
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


class _Provider:
    def __init__(self, *, complete: bool = True) -> None:
        self.complete = complete
        self.calls: list[str] = []

    async def read(
        self,
        *,
        definition: MetricSemanticDefinition,
        resource_id: str,
        start: datetime,
        end: datetime,
    ) -> MetricWindow:
        self.calls.append(resource_id)
        samples = (
            (
                MetricSample(timestamp=start + timedelta(minutes=1), value=10.0),
                MetricSample(timestamp=start + timedelta(minutes=2), value=20.0),
            )
            if self.complete
            else ()
        )
        return MetricWindow(
            concept_id=definition.concept_id,
            resource_id=resource_id,
            unit=definition.canonical_unit,
            start=start,
            end=end,
            samples=samples,
            complete=self.complete,
            evidence_refs=(f"metric-provider:{resource_id}",),
            missing_reason=None if self.complete else "provider_unavailable",
        )


async def _invoke(
    provider: _Provider,
    *,
    resource_count: int,
    window_seconds: int = 900,
) -> dict[str, object]:
    declaration = resource_metric_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        resource_metric_inventory_function(
            release,
            registry=REGISTRY,
            provider=provider,
            now=lambda: NOW,
        ),
    )
    result = await registry.invoke(
        RESOURCE_METRIC_FUNCTION_NAME,
        {
            "query_result": _query_result(resource_count).model_dump(mode="json"),
            "metric_concepts": ["resource.saturation"],
            "window_seconds": window_seconds,
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )
    assert isinstance(result, dict)
    return result


def test_metric_function_declares_bounded_no_authority_inputs() -> None:
    declaration = resource_metric_function_type()

    assert set(declaration.input_schema["properties"]) == {
        "query_result",
        "metric_concepts",
        "window_seconds",
    }
    assert declaration.required_role is CeilingRole.READER
    assert declaration.network_allowed is False
    assert declaration.credentials_allowed is False


async def test_metric_function_returns_exact_aggregated_observations() -> None:
    provider = _Provider()

    result = await _invoke(provider, resource_count=2)

    assert result["complete"] is True
    assert result["truncation_reason"] is None
    rows = result["rows"]
    assert isinstance(rows, list)
    assert len(rows) == 2
    assert rows[0]["values"]["value"] == 15.0
    assert rows[0]["values"]["sample_count"] == 2
    assert rows[0]["values"]["execution_authority"] is False
    assert provider.calls == ["resource-00", "resource-01"]


async def test_metric_function_accepts_one_bounded_seven_day_window() -> None:
    result = await _invoke(_Provider(), resource_count=1, window_seconds=604800)

    assert result["complete"] is True
    rows = result["rows"]
    assert isinstance(rows, list)
    assert rows[0]["values"]["window_start"] == (NOW - timedelta(days=7)).isoformat()


async def test_metric_function_preserves_provider_gaps_as_incomplete_rows() -> None:
    result = await _invoke(_Provider(complete=False), resource_count=1)

    assert result["complete"] is False
    assert result["truncation_reason"] == "provider_unavailable"
    rows = result["rows"]
    assert isinstance(rows, list)
    assert rows[0]["values"]["value"] is None
    assert rows[0]["values"]["complete"] is False
    assert rows[0]["values"]["missing_reason"] == "provider_unavailable"


async def test_metric_function_marks_collection_sampling_incomplete() -> None:
    provider = _Provider()

    result = await _invoke(provider, resource_count=17)

    assert result["complete"] is False
    assert result["truncation_reason"] == "resource_metric_scope_sampled"
    assert len(result["rows"]) == 16
    assert len(provider.calls) == 16
