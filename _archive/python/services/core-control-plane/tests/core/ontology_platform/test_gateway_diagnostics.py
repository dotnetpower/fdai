"""Synthetic gateway evidence checks; no live metrics, clouds, or database reads."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fdai.core.detection.series import MetricSample
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.gateway_diagnostics import (
    GATEWAY_DIAGNOSTIC_FUNCTION_NAME,
    MAX_GATEWAY_PROVIDER_READS,
    gateway_diagnostic_function,
    gateway_diagnostic_function_type,
    gateway_diagnostic_windows,
)
from fdai.core.ontology_platform.metric_semantics import (
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
from fdai.runtime.metric_semantic_catalog import load_metric_semantic_registry
from fdai.shared.contracts.models import CeilingRole, OntologyRelease
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyObjectRecord

NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)
WINDOWS = gateway_diagnostic_windows({}, evaluation_time=NOW)
REGISTRY = load_metric_semantic_registry(
    Path(__file__).resolve().parents[5] / "rule-catalog/vocabulary/metric-semantics.yaml",
)


def _resource(
    resource_id: str,
    resource_type: str,
    *,
    name: str | None = None,
    model_name: str | None = None,
) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=resource_id,
        object_type="Resource",
        properties={
            "id": resource_id,
            "name": name if name is not None else resource_id,
            "type": resource_type,
            **({"properties": {"model_name": model_name}} if model_name is not None else {}),
        },
    )


def _scope(
    release: OntologyRelease,
    objects: tuple[OntologyObjectRecord, ...],
    *,
    complete: bool = True,
) -> SecuredObjectSetQueryResult:
    materialization = ObjectSetMaterialization(
        definition=ObjectSetDefinition(
            selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
            as_of=NOW,
            purpose="operations-review",
            limit=16,
            include_relationships=False,
        ),
        graph=OntologyGraphSnapshot(
            objects=objects,
            links=(),
            truncated=False,
            source_complete=complete,
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
            returned_object_count=len(objects),
            returned_link_count=0,
            complete=complete,
            source_complete=complete,
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
    def __init__(self, mode: str = "observed") -> None:
        self.mode = mode
        self.calls: list[tuple[str, str, datetime, datetime]] = []
        self.active = 0
        self.maximum_active = 0

    async def read(
        self,
        *,
        definition: MetricSemanticDefinition,
        resource_id: str,
        start: datetime,
        end: datetime,
    ) -> MetricWindow:
        self.calls.append((resource_id, definition.concept_id, start, end))
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            if self.mode == "blocked":
                await asyncio.Event().wait()
            await asyncio.sleep(0)
            if self.mode == "error":
                raise OSError("synthetic provider failure")
            value = 10.0 if end == WINDOWS.baseline_end else 20.0
            if self.mode == "zero":
                value = 0.0
            complete = self.mode != "incomplete" and not (
                self.mode == "baseline_missing" and end == WINDOWS.baseline_end
            )
            window = MetricWindow(
                concept_id=definition.concept_id,
                resource_id=resource_id,
                unit=definition.canonical_unit,
                start=start,
                end=end,
                samples=(
                    ()
                    if self.mode == "empty"
                    else (MetricSample(timestamp=start + timedelta(seconds=60), value=value),)
                ),
                complete=complete,
                missing_reason=None if complete else "provider_gap",
                evidence_refs=(f"metric:{resource_id}:{definition.concept_id}:{end.isoformat()}",),
            )
            if self.mode == "many":
                return replace(
                    window,
                    samples=tuple(
                        MetricSample(timestamp=start + (end - start) * (n + 1) / 1002, value=value)
                        for n in range(1001)
                    ),
                )
            if self.mode == "wrong_resource":
                return replace(window, resource_id="other-resource")
            if self.mode == "wrong_unit":
                return replace(window, unit="incompatible")
            if self.mode == "wrong_window":
                return replace(window, end=end + timedelta(seconds=1))
            if self.mode == "wrong_concept":
                return replace(window, concept_id="unrequested.metric")
            return window
        finally:
            self.active -= 1


async def _invoke(
    provider: _Provider,
    *,
    root_type: str = "network.application-gateway",
    root_count: int = 1,
    backend_types: tuple[str, ...] = ("llm-model-deployment",),
    root_complete: bool = True,
    backend_complete: bool = True,
    authorized: bool = True,
    registry: MetricSemanticRegistry = REGISTRY,
    read_timeout_seconds: float = 4,
    total_timeout_seconds: float = 20,
    backend_objects: tuple[OntologyObjectRecord, ...] | None = None,
    requested_filter: dict[str, object] | None = None,
    requested_objects: tuple[OntologyObjectRecord, ...] | None = None,
    requested_complete: bool = True,
    requested_transform: Callable[[SecuredObjectSetQueryResult], SecuredObjectSetQueryResult]
    | None = None,
) -> dict[str, Any]:
    declaration = gateway_diagnostic_function_type()
    release = build_ontology_release(function_types=(declaration,))
    root = _scope(
        release,
        tuple(_resource(f"example-gateway-{n}", root_type) for n in range(root_count)),
        complete=root_complete,
    )
    backends = _scope(
        release,
        (
            backend_objects
            if backend_objects is not None
            else tuple(
                _resource(f"example-backend-{n}", kind) for n, kind in enumerate(backend_types)
            )
        ),
        complete=backend_complete,
    )
    requested = (
        _scope(release, requested_objects, complete=requested_complete)
        if requested_objects is not None
        else None
    )
    if requested is not None and requested_transform is not None:
        requested = requested_transform(requested)
    arguments: dict[str, object] = {
        "query_result": root.model_dump(mode="json"),
        "backend_query_result": backends.model_dump(mode="json"),
        **WINDOWS.arguments(),
    }
    if requested_filter is not None:
        if set(requested_filter) == {"field", "value"}:
            arguments["requested_backend_filter_field"] = requested_filter["field"]
            arguments["requested_backend_filter_value"] = requested_filter["value"]
        else:
            arguments.update(requested_filter)
    if requested is not None:
        arguments["requested_backend_query_result"] = requested.model_dump(mode="json")
    functions = OntologyFunctionRegistry(release=release)
    functions.register_contextual(
        declaration,
        gateway_diagnostic_function(
            release,
            registry=registry,
            provider=provider,
            read_timeout_seconds=read_timeout_seconds,
            total_timeout_seconds=total_timeout_seconds,
        ),
    )
    result = await functions.invoke(
        GATEWAY_DIAGNOSTIC_FUNCTION_NAME,
        arguments,
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
            evidence_refs=(
                (
                    root.receipt.projected_result_digest,
                    backends.receipt.projected_result_digest,
                    *(
                        (requested.receipt.projected_result_digest,)
                        if requested is not None
                        else ()
                    ),
                )
                if authorized
                else ()
            ),
        ),
    )
    assert isinstance(result, dict)
    return result


def _metric_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row["values"] for row in result["rows"] if row["values"]["row_kind"] == "metric_comparison"
    ]


@pytest.mark.parametrize(
    "root_type,prefix,expected_rows",
    [
        ("network.application-gateway", "gateway.", 14),
        ("api-gateway", "api_gateway.", 16),
    ],
)
async def test_gateway_profiles_use_verified_type_and_identical_windows(
    root_type: str,
    prefix: str,
    expected_rows: int,
) -> None:
    provider = _Provider()
    result = await _invoke(provider, root_type=root_type)
    rows = _metric_rows(result)
    assert result["complete"] is True
    assert len(rows) == expected_rows
    assert provider.maximum_active <= 4
    assert len(provider.calls) == expected_rows * 2
    assert {call[2:] for call in provider.calls} == {
        (WINDOWS.baseline_start, WINDOWS.baseline_end),
        (WINDOWS.current_start, WINDOWS.current_end),
    }
    assert all(row["metric_concept"].startswith(prefix) for row in rows if row["role"] == "gateway")
    assert all(
        row["metric_concept"].startswith("model.") for row in rows if row["role"] == "backend"
    )
    assert all(row["baseline_value"] == 10 and row["current_value"] == 20 for row in rows)
    assert all(row["absolute_change"] == 10 and row["trend"] == "increased" for row in rows)
    assert all(row["baseline_sample_count"] == row["current_sample_count"] == 1 for row in rows)
    assert all(row["evidence_refs"] for row in rows)
    assert all(not row["cause_claim_supported"] and not row["execution_authority"] for row in rows)
    limits = result["rows"][0]["values"]["interpretation_limits"]
    assert "status counts do not prove policy or cause" in limits
    assert "tokens measure consumption, not capacity" in limits


async def test_apim_profile_separates_gateway_and_backend_status_codes() -> None:
    provider = _Provider()
    result = await _invoke(provider, root_type="api-gateway")

    gateway_concepts = {
        row["metric_concept"] for row in _metric_rows(result) if row["role"] == "gateway"
    }
    assert {
        "api_gateway.response.429.count",
        "api_gateway.response.500.count",
        "api_gateway.response.503.count",
        "api_gateway.backend.response.429.count",
        "api_gateway.backend.response.500.count",
        "api_gateway.backend.response.503.count",
    } <= gateway_concepts
    assert result["rows"][0]["values"]["profile_excluded_concepts"] == []


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("empty", "metric_samples_missing"),
        ("incomplete", "metric_window_incomplete"),
        ("wrong_resource", "metric_scope_mismatch"),
        ("wrong_unit", "metric_scope_mismatch"),
        ("wrong_window", "metric_scope_mismatch"),
        ("wrong_concept", "metric_scope_mismatch"),
        ("error", "metric_provider_unavailable"),
        ("many", "metric_sample_limit_exceeded"),
    ],
)
async def test_gateway_missing_or_mismatched_metrics_never_become_zero_or_healthy(
    mode: str,
    reason: str,
) -> None:
    result = await _invoke(_Provider(mode))
    assert result["complete"] is False
    for row in _metric_rows(result):
        assert row["reason"] == reason
        assert row["baseline_value"] is row["current_value"] is None
        assert row["trend"] == "unknown"
        assert row["cause_claim_supported"] is False


async def test_gateway_observed_zero_is_distinct_from_missing() -> None:
    result = await _invoke(_Provider("zero"))
    assert result["complete"] is True
    for row in _metric_rows(result):
        assert row["current_value"] == row["baseline_value"] == 0
        assert row["trend"] == "unchanged_observed_value"
        assert row["relative_change"] is None


async def test_gateway_retains_independent_current_values_without_inventing_a_baseline() -> None:
    result = await _invoke(_Provider("baseline_missing"))
    assert result["complete"] is False
    for row in _metric_rows(result):
        assert row["baseline_value"] is None
        assert row["current_value"] == 20
        assert row["absolute_change"] is row["relative_change"] is None
        assert row["trend"] == "unknown"


@pytest.mark.parametrize(
    "root_count,root_type,complete",
    [
        (0, "network.application-gateway", True),
        (2, "network.application-gateway", True),
        (1, "compute.vm", True),
        (1, "network.application-gateway", False),
    ],
)
async def test_gateway_requires_exactly_one_complete_actual_gateway(
    root_count: int,
    root_type: str,
    complete: bool,
) -> None:
    provider = _Provider()
    result = await _invoke(
        provider, root_count=root_count, root_type=root_type, root_complete=complete
    )
    assert result["complete"] is False
    assert provider.calls == []


@pytest.mark.parametrize(
    "backend_types,complete,reason",
    [
        ((), True, "no_observed_routes_to_relationship"),
        (("llm-endpoint",), False, "backend_resource_scope_incomplete"),
        (("llm-endpoint",) * 5, True, "backend_resource_limit_exceeded"),
        (("unsupported.resource",), True, "backend_metric_profile_unsupported"),
    ],
)
async def test_gateway_backend_gaps_are_explicit_without_silent_sampling(
    backend_types: tuple[str, ...],
    complete: bool,
    reason: str,
) -> None:
    provider = _Provider()
    result = await _invoke(provider, backend_types=backend_types, backend_complete=complete)
    assert result["complete"] is False
    assert reason in result["truncation_reason"]
    assert all(call[0].startswith("example-gateway-") for call in provider.calls)


async def test_apim_absent_relationship_is_unresolved_not_invented() -> None:
    result = await _invoke(_Provider(), root_type="api-gateway", backend_types=())
    assert "api_gateway_backend_mapping_unresolved" in result["truncation_reason"]
    assert result["complete"] is False


async def test_gateway_maximum_profile_keeps_shared_concurrency_and_read_bounds() -> None:
    provider = _Provider()
    result = await _invoke(provider, backend_types=("llm-model-deployment",) * 4)
    assert result["complete"] is True
    assert len(provider.calls) == 70
    assert len(provider.calls) <= MAX_GATEWAY_PROVIDER_READS
    assert provider.maximum_active <= 4
    assert len(_metric_rows(result)) == 35


async def test_apim_maximum_profile_fits_the_fixed_provider_read_bound() -> None:
    provider = _Provider()
    result = await _invoke(
        provider,
        root_type="api-gateway",
        backend_types=("llm-model-deployment",) * 4,
    )
    assert result["complete"] is True
    assert len(provider.calls) == MAX_GATEWAY_PROVIDER_READS
    assert provider.maximum_active <= 4
    assert len(_metric_rows(result)) == 37


async def test_gateway_compute_backend_profiles_do_not_use_model_or_gateway_concepts() -> None:
    provider = _Provider()
    result = await _invoke(provider, backend_types=("compute.vm", "compute.container-app"))
    assert result["complete"] is True
    rows = [row for row in _metric_rows(result) if row["role"] == "backend"]
    assert {row["metric_concept"] for row in rows} == {
        "resource.cpu.utilization_pct",
        "resource.memory.available_pct",
        "resource.saturation",
        "request.timeout",
        "resource.activation.failure",
    }


@pytest.mark.parametrize(
    "read_timeout,total_timeout,reason",
    [
        (0.001, 1, "metric_read_timeout"),
        (1, 0.001, "diagnostic_deadline_exceeded"),
    ],
)
async def test_gateway_deadlines_cancel_pending_reads_without_retries(
    read_timeout: float,
    total_timeout: float,
    reason: str,
) -> None:
    provider = _Provider("blocked")
    result = await _invoke(
        provider,
        read_timeout_seconds=read_timeout,
        total_timeout_seconds=total_timeout,
    )
    assert result["complete"] is False
    assert reason in result["truncation_reason"]
    assert provider.active == 0
    assert len(provider.calls) == len(set(provider.calls))
    assert provider.maximum_active <= 4


async def test_gateway_requires_process_issued_scope_markers_before_any_metric_read() -> None:
    provider = _Provider()
    with pytest.raises(PermissionError):
        await _invoke(provider, authorized=False)
    assert provider.calls == []


async def test_gateway_missing_catalog_concepts_are_reported_without_substitution() -> None:
    registry = MetricSemanticRegistry.build((REGISTRY.resolve("gateway.total_time"),))
    provider = _Provider()
    result = await _invoke(provider, registry=registry)
    assert result["complete"] is False
    assert "metric_concept_unavailable" in result["truncation_reason"]
    assert len(provider.calls) == 2
    assert all(call[1] == "gateway.total_time" for call in provider.calls)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "example-deployment-a"),
        ("name", "example-backend-a"),
        ("model_name", "example-model"),
    ],
)
async def test_requested_backend_prefers_and_narrows_a_unique_observed_path_match(
    field: str,
    value: str,
) -> None:
    wanted = _resource(
        "example-deployment-a",
        "llm-model-deployment",
        name="example-backend-a",
        model_name="example-model",
    )
    other = _resource("example-deployment-b", "llm-model-deployment", model_name="other-model")
    outside = _resource("example-deployment-c", "llm-model-deployment", model_name="example-model")
    provider = _Provider()
    result = await _invoke(
        provider,
        backend_objects=(wanted, other),
        requested_filter={"field": field, "value": value},
        requested_objects=(wanted, outside),
    )
    assert result["complete"] is True
    assert {call[0] for call in provider.calls} == {"example-gateway-0", wanted.id}
    backend_rows = [row for row in _metric_rows(result) if row["role"] == "backend"]
    assert len(backend_rows) == 7
    assert all(row["relationship_unverified"] is False for row in backend_rows)
    assert result["rows"][0]["values"]["selected_backend_count"] == 1
    assert result["rows"][0]["values"]["requested_comparison_count"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "example-deployment-a"),
        ("name", "example-backend-a"),
        ("model_name", "example-model"),
    ],
)
async def test_requested_model_outside_apim_path_is_a_separate_comparison_not_a_link(
    field: str,
    value: str,
) -> None:
    wanted = _resource(
        "example-deployment-a",
        "llm-model-deployment",
        name="example-backend-a",
        model_name="example-model",
    )
    provider = _Provider()
    result = await _invoke(
        provider,
        root_type="api-gateway",
        backend_objects=(),
        requested_filter={"field": field, "value": value},
        requested_objects=(wanted,),
    )
    assert result["complete"] is False
    assert "relationship_unverified" in result["truncation_reason"]
    assert "api_gateway_backend_mapping_unresolved" in result["truncation_reason"]
    comparisons = [row for row in _metric_rows(result) if row["role"] == "requested_comparison"]
    assert len(comparisons) == 7
    assert all(
        row["resource_id"] == wanted.id and row["relationship_unverified"] for row in comparisons
    )
    assert all(
        row["comparison_complete"] and not row["cause_claim_supported"] for row in comparisons
    )
    assert all(not row["execution_authority"] for row in comparisons)
    assert not any(row["role"] == "backend" for row in _metric_rows(result))
    assert {call[2:] for call in provider.calls} == {
        (WINDOWS.baseline_start, WINDOWS.baseline_end),
        (WINDOWS.current_start, WINDOWS.current_end),
    }


@pytest.mark.parametrize(
    "model_names,reason",
    [
        ((), "requested_backend_not_found"),
        (("example-model", "example-model"), "requested_backend_ambiguous"),
        (("EXAMPLE-MODEL",), "requested_backend_not_found"),
        (("example-model-extended",), "requested_backend_not_found"),
        (("example-model", None), "requested_backend_identity_unavailable"),
        (("example-model",) + ("other-model",) * 16, "requested_backend_resource_limit_exceeded"),
    ],
)
async def test_requested_model_never_guesses_or_picks_from_ambiguous_or_incomplete_identity(
    model_names: tuple[str | None, ...],
    reason: str,
) -> None:
    candidates = tuple(
        _resource(f"example-deployment-{index}", "llm-model-deployment", model_name=model_name)
        for index, model_name in enumerate(model_names)
    )
    provider = _Provider()
    result = await _invoke(
        provider,
        backend_objects=(),
        requested_filter={"field": "model_name", "value": "example-model"},
        requested_objects=candidates,
    )
    assert result["complete"] is False and reason in result["truncation_reason"]
    assert all(call[0] == "example-gateway-0" for call in provider.calls)
    assert not any(row["role"] == "requested_comparison" for row in _metric_rows(result))


async def test_requested_backend_requires_complete_candidates_before_declaring_a_unique_match() -> (
    None
):
    provider = _Provider()
    result = await _invoke(
        provider,
        backend_objects=(),
        requested_filter={"field": "id", "value": "example-deployment"},
        requested_objects=(_resource("example-deployment", "llm-model-deployment"),),
        requested_complete=False,
    )
    assert "requested_backend_resource_scope_incomplete" in result["truncation_reason"]
    assert all(call[0] == "example-gateway-0" for call in provider.calls)


async def test_ambiguous_observed_backend_cannot_be_replaced_by_fallback() -> None:
    objects = tuple(
        _resource(f"example-deployment-{index}", "llm-model-deployment", model_name="example-model")
        for index in range(2)
    )
    provider = _Provider()
    result = await _invoke(
        provider,
        backend_objects=objects,
        requested_objects=(objects[0],),
        requested_filter={"field": "model_name", "value": "example-model"},
    )
    assert "requested_backend_ambiguous" in result["truncation_reason"]
    assert all(call[0] == "example-gateway-0" for call in provider.calls)


async def test_requested_backend_does_not_reuse_the_gateway_as_its_own_comparison() -> None:
    provider = _Provider()
    result = await _invoke(
        provider,
        backend_objects=(),
        requested_filter={"field": "id", "value": "example-gateway-0"},
        requested_objects=(_resource("example-gateway-0", "network.application-gateway"),),
    )
    assert "requested_backend_is_gateway" in result["truncation_reason"]
    assert len(provider.calls) == 14
    assert len(provider.calls) == len(set(provider.calls))


def _change_requested_scope(
    scope: SecuredObjectSetQueryResult,
    change: str,
) -> SecuredObjectSetQueryResult:
    definition = scope.materialization.definition
    receipt = scope.receipt
    if change == "cutoff":
        definition = definition.model_copy(update={"as_of": NOW - timedelta(minutes=1)})
        receipt = receipt.model_copy(update={"observation_cutoff": NOW - timedelta(minutes=1)})
    elif change == "role":
        receipt = receipt.model_copy(update={"caller_role": CeilingRole.OWNER})
    elif change == "purpose":
        definition = definition.model_copy(update={"purpose": "other-review"})
        receipt = receipt.model_copy(update={"purpose": "other-review"})
    elif change == "release":
        declaration = gateway_diagnostic_function_type().model_copy(update={"version": "9.0.0"})
        receipt = receipt.model_copy(
            update={
                "ontology_release": build_ontology_release(function_types=(declaration,)).ref(),
            }
        )
    materialization = scope.materialization.model_copy(update={"definition": definition})
    receipt = receipt.model_copy(
        update={"projected_result_digest": _projected_result_digest(materialization)}
    )
    return SecuredObjectSetQueryResult(materialization=materialization, receipt=receipt)


@pytest.mark.parametrize(
    "change,error",
    [
        ("cutoff", ValueError),
        ("role", PermissionError),
        ("purpose", PermissionError),
        ("release", PermissionError),
    ],
)
async def test_requested_backend_scope_retains_current_release_role_purpose_and_cutoff(
    change: str,
    error: type[Exception],
) -> None:
    provider = _Provider()
    with pytest.raises(error):
        await _invoke(
            provider,
            backend_objects=(),
            requested_filter={"field": "id", "value": "example-deployment"},
            requested_objects=(_resource("example-deployment", "llm-model-deployment"),),
            requested_transform=lambda scope: _change_requested_scope(scope, change),
        )
    assert provider.calls == []


@pytest.mark.parametrize(
    "requested_filter",
    [
        {"field": "type", "value": "llm-model-deployment"},
        {"field": "model_name", "value": ""},
        {"field": "model_name", "value": " "},
        {"field": "model_name", "value": "x" * 257},
        {"field": "name", "value": "example", "execution_authority": True},
    ],
)
async def test_requested_backend_filter_is_validated_as_data_not_authority(
    requested_filter: dict[str, object],
) -> None:
    provider = _Provider()
    with pytest.raises(ValueError):
        await _invoke(provider, requested_filter=requested_filter, requested_objects=())
    assert provider.calls == []


async def test_requested_backend_scope_cannot_be_supplied_without_an_explicit_filter() -> None:
    provider = _Provider()
    with pytest.raises(ValueError):
        await _invoke(provider, requested_objects=())
    assert provider.calls == []


def test_requested_backend_scope_remains_dependency_only_in_function_schema() -> None:
    schema = gateway_diagnostic_function_type().input_schema
    assert schema["properties"]["requested_backend_query_result"]["x-fdai-dependency-only"] is True
    assert schema["properties"]["requested_backend_filter_field"]["type"] == "string"
    assert schema["properties"]["requested_backend_filter_value"]["type"] == "string"


async def test_requested_backend_filter_can_narrow_an_issued_path_without_a_fallback_scope() -> (
    None
):
    wanted = _resource("example-deployment", "llm-model-deployment", model_name="example-model")
    result = await _invoke(
        _Provider(),
        backend_objects=(wanted,),
        requested_filter={"field": "model_name", "value": "example-model"},
    )
    assert result["complete"] is True
    assert result["rows"][0]["values"]["requested_backend_resolution_scope"] == "observed_path_only"


async def test_missing_backend_path_without_fallback_remains_unknown() -> None:
    result = await _invoke(
        _Provider(),
        backend_objects=(),
        backend_complete=False,
        requested_filter={"field": "model_name", "value": "example-model"},
    )
    assert "requested_backend_unresolved" in result["truncation_reason"]
    assert "requested_backend_not_found" not in result["truncation_reason"]


async def test_requested_model_name_uses_only_the_canonical_projected_property() -> None:
    raw_provider_shape = OntologyObjectRecord(
        id="example-deployment",
        object_type="Resource",
        properties={
            "id": "example-deployment",
            "type": "llm-model-deployment",
            "properties": {"model": {"name": "example-model"}},
        },
    )
    provider = _Provider()
    result = await _invoke(
        provider,
        backend_objects=(),
        requested_objects=(raw_provider_shape,),
        requested_filter={"field": "model_name", "value": "example-model"},
    )
    assert "requested_backend_identity_unavailable" in result["truncation_reason"]
    assert all(call[0] == "example-gateway-0" for call in provider.calls)
