"""Verified Resource metric collection FunctionType tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
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
    RESOURCE_METRIC_SERIES_FUNCTION_NAME,
    resource_metric_function_type,
    resource_metric_inventory_function,
    resource_metric_series_function,
    resource_metric_series_function_type,
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
    def __init__(self, *, complete: bool = True, values: dict[str, float] | None = None) -> None:
        self.complete = complete
        # A resource listed with a value reads that constant; any other reads 10 and 20.
        self.values = values or {}
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
        complete = self.complete and self.values.get(resource_id, 0.0) >= 0
        constant = self.values.get(resource_id)
        samples = (
            (
                MetricSample(
                    timestamp=start + timedelta(minutes=1),
                    value=10.0 if constant is None else constant,
                ),
                MetricSample(
                    timestamp=start + timedelta(minutes=2),
                    value=20.0 if constant is None else constant,
                ),
            )
            if complete
            else ()
        )
        return MetricWindow(
            concept_id=definition.concept_id,
            resource_id=resource_id,
            unit=definition.canonical_unit,
            start=start,
            end=end,
            samples=samples,
            complete=complete,
            evidence_refs=(f"metric-provider:{resource_id}",),
            missing_reason=None
            if complete
            else ("provider_unavailable" if not self.complete else "provider_gap"),
        )


async def _invoke(
    provider: _Provider,
    *,
    resource_count: int,
    window_seconds: int = 900,
    **selection: object,
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
            **selection,
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )
    assert isinstance(result, dict)
    return result


class _SeriesProvider(_Provider):
    async def read(
        self,
        *,
        definition: MetricSemanticDefinition,
        resource_id: str,
        start: datetime,
        end: datetime,
    ) -> MetricWindow:
        self.calls.append(resource_id)
        span = end - start
        samples = tuple(
            MetricSample(
                timestamp=start + span * (index + 1) / 46,
                value=999.0 if index == 22 else float(index),
            )
            for index in range(45)
        )
        return MetricWindow(
            concept_id=definition.concept_id,
            resource_id=resource_id,
            unit=definition.canonical_unit,
            start=start,
            end=end,
            samples=samples,
            complete=True,
            evidence_refs=(f"metric-provider:{resource_id}",),
        )


async def _invoke_series(
    provider: _Provider,
    *,
    resource_count: int,
    window_seconds: int = 900,
) -> dict[str, object]:
    declaration = resource_metric_series_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        resource_metric_series_function(
            release,
            registry=REGISTRY,
            provider=provider,
            now=lambda: NOW,
        ),
    )
    result = await registry.invoke(
        RESOURCE_METRIC_SERIES_FUNCTION_NAME,
        {
            "query_result": _query_result(resource_count).model_dump(mode="json"),
            "metric_concept": "resource.saturation",
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
        "comparator",
        "threshold",
        "threshold_unit",
        "order_direction",
        "order_limit",
        "list_unknown",
    }
    assert declaration.version == "1.2.0"
    assert declaration.required_role is CeilingRole.READER
    assert declaration.network_allowed is False
    assert declaration.credentials_allowed is False


def test_metric_series_function_declares_exact_bounded_no_authority_inputs() -> None:
    declaration = resource_metric_series_function_type()

    assert set(declaration.input_schema["properties"]) == {
        "query_result",
        "metric_concept",
        "window_seconds",
    }
    assert declaration.output_schema["properties"]["rows"]["maxItems"] == 20
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
    # The provider failure also stops any later batch, so both reasons are stated.
    assert result["truncation_reason"] == "metric_provider_unavailable+provider_unavailable"
    rows = result["rows"]
    assert isinstance(rows, list)
    assert rows[0]["values"]["value"] is None
    assert rows[0]["values"]["complete"] is False
    assert rows[0]["values"]["missing_reason"] == "provider_unavailable"


async def test_metric_function_reads_every_member_without_sampling() -> None:
    provider = _Provider()

    result = await _invoke(provider, resource_count=17)

    assert result["complete"] is True
    assert len(result["rows"]) == 17
    assert len(provider.calls) == 17


async def test_metric_function_stops_at_its_reserved_budget_and_says_so() -> None:
    provider = _Provider()

    result = await _invoke(provider, resource_count=140)

    # Whole batches of 16 run until the next would exceed 128 reads; none is sampled.
    assert len(provider.calls) == 128
    assert len(result["rows"]) == 128
    assert result["complete"] is False
    assert result["truncation_reason"] == "metric_budget_exhausted"


_VALUES = {"resource-00": 95.0, "resource-01": 40.0, "resource-02": 91.0, "resource-03": -1.0}


async def test_a_threshold_keeps_only_complete_matching_members_and_lists_the_unknown() -> None:
    result = await _invoke(
        _Provider(values=_VALUES),
        resource_count=4,
        comparator="gt",
        threshold="90",
        threshold_unit="nanocores",
        list_unknown=True,
    )

    rows = [row["values"] for row in result["rows"]]
    assert [(row["name"], row["metric_status"]) for row in rows] == [
        ("service-00", "measured"),
        ("service-02", "measured"),
        ("service-03", "unknown_incomplete"),
    ]
    assert rows[2]["value"] is None and rows[2]["missing_reason"] == "provider_gap"
    assert result["complete"] is False
    assert result["truncation_reason"] == "provider_gap"


async def test_a_rank_orders_complete_values_only_and_applies_a_stated_limit() -> None:
    ranked = await _invoke(
        _Provider(values=_VALUES),
        resource_count=4,
        order_direction="descending",
        order_limit=2,
        list_unknown=True,
    )
    whole = await _invoke(
        _Provider(values={"resource-00": 5.0, "resource-01": 7.0}),
        resource_count=2,
        order_direction="ascending",
    )

    rows = [row["values"] for row in ranked["rows"]]
    assert [(row["name"], row.get("rank")) for row in rows] == [
        ("service-00", 1),
        ("service-02", 2),
        ("service-03", None),
    ]
    assert [row["values"]["name"] for row in whole["rows"]] == ["service-00", "service-01"]
    assert whole["complete"] is True


async def test_a_comparison_needs_the_canonical_unit_and_one_concept() -> None:
    with pytest.raises(Exception, match="canonical unit"):
        await _invoke(
            _Provider(),
            resource_count=1,
            comparator="gt",
            threshold="90",
            threshold_unit="percent",
        )
    with pytest.raises(Exception, match="comparison or an order"):
        await _invoke(_Provider(), resource_count=1, list_unknown=True)


async def test_metric_series_function_projects_ordered_spike_preserving_points() -> None:
    provider = _SeriesProvider()

    result = await _invoke_series(provider, resource_count=1, window_seconds=604800)

    assert result["complete"] is True
    assert result["truncation_reason"] is None
    rows = result["rows"]
    assert isinstance(rows, list)
    assert len(rows) == 20
    values = [row["values"] for row in rows]
    timestamps = [value["timestamp"] for value in values]
    assert timestamps == sorted(timestamps)
    assert 999.0 in {value["value"] for value in values}
    assert all(value["source_sample_count"] == 45 for value in values)
    assert all(value["displayed_sample_count"] == 20 for value in values)
    assert all(value["sampling_strategy"] == "min_max_envelope_v1" for value in values)
    assert all(value["execution_authority"] is False for value in values)
    assert provider.calls == ["resource-00"]


async def test_metric_series_function_rejects_ambiguous_resource_before_provider_read() -> None:
    provider = _SeriesProvider()

    result = await _invoke_series(provider, resource_count=2)

    assert result["complete"] is False
    assert result["truncation_reason"] == "resource_identity_ambiguous"
    assert result["rows"] == []
    assert provider.calls == []
