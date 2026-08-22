"""Read-only FunctionType for bounded metric observations over a Resource collection."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from fdai.core.detection.series import MetricSample
from fdai.core.ontology_platform.functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
)
from fdai.core.ontology_platform.metric_semantics import (
    MetricAggregation,
    MetricSemanticDefinition,
    MetricSemanticRegistry,
    MetricWindow,
    MetricWindowProvider,
)
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

RESOURCE_METRIC_FUNCTION_NAME = "query.resource_metric_inventory"
RESOURCE_METRIC_SERIES_FUNCTION_NAME = "query.resource_metric_series"
MAX_RESOURCE_METRIC_WINDOW_SECONDS = 7 * 24 * 60 * 60
_MAX_CONCEPTS = 4
_MAX_RESOURCES = 16
_MAX_CONCURRENT_READS = 4
_MAX_SERIES_POINTS = 20


def resource_metric_function_type() -> OntologyFunctionType:
    """Declare bounded current metric reads over an already secured Resource set."""

    return OntologyFunctionType(
        name=RESOURCE_METRIC_FUNCTION_NAME,
        version="1.1.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query_result", "metric_concepts", "window_seconds"],
            "properties": {
                "query_result": {"type": "object"},
                "metric_concepts": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": _MAX_CONCEPTS,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": r"^[a-z][a-z0-9_.-]{0,127}$",
                    },
                },
                "window_seconds": {
                    "type": "integer",
                    "minimum": 300,
                    "maximum": MAX_RESOURCE_METRIC_WINDOW_SECONDS,
                },
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "properties": {
                "rows": {"type": "array", "maxItems": _MAX_RESOURCES * _MAX_CONCEPTS},
                "complete": {"type": "boolean"},
                "truncation_reason": {"type": ["string", "null"]},
            },
        },
        read_sets=["Resource"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=["operations-review"],
        timeout_seconds=30,
        cpu_millis=500,
        memory_bytes=67_108_864,
        max_output_bytes=1_048_576,
        network_allowed=False,
        credentials_allowed=False,
    )


def resource_metric_series_function_type() -> OntologyFunctionType:
    """Declare one bounded exact-resource metric series read."""

    return OntologyFunctionType(
        name=RESOURCE_METRIC_SERIES_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query_result", "metric_concept", "window_seconds"],
            "properties": {
                "query_result": {"type": "object"},
                "metric_concept": {
                    "type": "string",
                    "pattern": r"^[a-z][a-z0-9_.-]{0,127}$",
                },
                "window_seconds": {
                    "type": "integer",
                    "minimum": 300,
                    "maximum": MAX_RESOURCE_METRIC_WINDOW_SECONDS,
                },
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "properties": {
                "rows": {"type": "array", "maxItems": _MAX_SERIES_POINTS},
                "complete": {"type": "boolean"},
                "truncation_reason": {"type": ["string", "null"]},
            },
        },
        read_sets=["Resource"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=["operations-review"],
        timeout_seconds=30,
        cpu_millis=500,
        memory_bytes=67_108_864,
        max_output_bytes=1_048_576,
        network_allowed=False,
        credentials_allowed=False,
    )


def resource_metric_inventory_function(
    ontology_release: OntologyRelease,
    *,
    registry: MetricSemanticRegistry,
    provider: MetricWindowProvider,
    now: Callable[[], datetime] | None = None,
) -> ContextualOntologyFunction:
    """Read exact reviewed metrics and preserve every provider gap as incomplete."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        RESOURCE_METRIC_FUNCTION_NAME,
    )
    clock = now or (lambda: datetime.now(UTC))

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("resource metric purpose does not match invocation context")
        secured = SecuredObjectSetQueryResult.model_validate(arguments["query_result"])
        if secured.receipt.truncated or not secured.receipt.complete:
            return _table((), complete=False, reason="resource_scope_incomplete")
        objects = tuple(sorted(secured.materialization.graph.objects, key=lambda item: item.id))
        if not objects:
            return _table((), complete=True, reason=None)
        selected = objects[:_MAX_RESOURCES]
        scope_sampled = len(objects) > _MAX_RESOURCES
        concept_ids = tuple(str(item) for item in arguments["metric_concepts"])
        definitions = tuple(registry.resolve(item) for item in concept_ids)
        window_seconds = int(arguments["window_seconds"])
        end = clock()
        if end.tzinfo is None:
            raise ValueError("resource metric clock MUST be timezone-aware")
        end = end.astimezone(UTC)
        start = end - timedelta(seconds=window_seconds)
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_READS)

        async def read(
            target_id: str,
            definition: MetricSemanticDefinition,
        ) -> MetricWindow:
            async with semaphore:
                result = await provider.read(
                    definition=definition,
                    resource_id=target_id,
                    start=start,
                    end=end,
                )
            if (
                result.resource_id != target_id
                or result.concept_id != definition.concept_id
                or result.unit != definition.canonical_unit
                or result.start != start
                or result.end != end
            ):
                raise ValueError("metric provider widened the verified collection request")
            return result

        windows = await asyncio.gather(
            *(read(target.id, definition) for target in selected for definition in definitions)
        )
        targets = {target.id: target for target in selected}
        rows: list[QueryRow] = []
        incomplete_reasons: list[str] = []
        for window in windows:
            target = targets[window.resource_id]
            definition = registry.resolve(window.concept_id)
            value = _aggregate(window, definition.aggregation) if window.complete else None
            if not window.complete:
                incomplete_reasons.append(window.missing_reason or "metric_window_incomplete")
            rows.append(
                QueryRow.from_values(
                    f"resource-metric-{len(rows) + 1:04d}",
                    {
                        "name": _text(target.properties.get("name")),
                        "type": _text(target.properties.get("type")),
                        "metric_concept": window.concept_id,
                        "value": value,
                        "unit": window.unit,
                        "aggregation": definition.aggregation.value,
                        "sample_count": len(window.samples),
                        "window_start": window.start.isoformat(),
                        "window_end": window.end.isoformat(),
                        "complete": window.complete,
                        "missing_reason": window.missing_reason,
                        "evidence_refs": list(window.evidence_refs),
                        "execution_authority": False,
                    },
                )
            )
        if scope_sampled:
            incomplete_reasons.append("resource_metric_scope_sampled")
        complete = not incomplete_reasons
        return _table(
            tuple(rows),
            complete=complete,
            reason=(None if complete else "+".join(sorted(set(incomplete_reasons)))),
        )

    return evaluate


def resource_metric_series_function(
    ontology_release: OntologyRelease,
    *,
    registry: MetricSemanticRegistry,
    provider: MetricWindowProvider,
    now: Callable[[], datetime] | None = None,
) -> ContextualOntologyFunction:
    """Read one exact reviewed metric and project a bounded display series."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        RESOURCE_METRIC_SERIES_FUNCTION_NAME,
    )
    clock = now or (lambda: datetime.now(UTC))

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("resource metric purpose does not match invocation context")
        secured = SecuredObjectSetQueryResult.model_validate(arguments["query_result"])
        if secured.receipt.truncated or not secured.receipt.complete:
            return _table((), complete=False, reason="resource_scope_incomplete")
        objects = tuple(sorted(secured.materialization.graph.objects, key=lambda item: item.id))
        if not objects:
            return _table((), complete=False, reason="resource_not_found")
        if len(objects) != 1:
            return _table((), complete=False, reason="resource_identity_ambiguous")
        target = objects[0]
        definition = registry.resolve(str(arguments["metric_concept"]))
        window_seconds = int(arguments["window_seconds"])
        end = clock()
        if end.tzinfo is None:
            raise ValueError("resource metric clock MUST be timezone-aware")
        end = end.astimezone(UTC)
        start = end - timedelta(seconds=window_seconds)
        window = await provider.read(
            definition=definition,
            resource_id=target.id,
            start=start,
            end=end,
        )
        if (
            window.resource_id != target.id
            or window.concept_id != definition.concept_id
            or window.unit != definition.canonical_unit
            or window.start != start
            or window.end != end
        ):
            raise ValueError("metric provider widened the verified series request")
        if not window.complete:
            return _table(
                (),
                complete=False,
                reason=window.missing_reason or "metric_window_incomplete",
            )
        display_samples = _metric_display_samples(window.samples)
        strategy = "min_max_envelope_v1" if len(display_samples) < len(window.samples) else "none"
        rows = tuple(
            QueryRow.from_values(
                f"resource-metric-sample-{index:04d}",
                {
                    "name": _text(target.properties.get("name")),
                    "type": _text(target.properties.get("type")),
                    "timestamp": sample.timestamp.isoformat(),
                    "value": sample.value,
                    "metric": window.concept_id,
                    "unit": window.unit,
                    "source_sample_count": len(window.samples),
                    "displayed_sample_count": len(display_samples),
                    "sampling_strategy": strategy,
                    "evidence_refs": list(window.evidence_refs),
                    "execution_authority": False,
                },
            )
            for index, sample in enumerate(display_samples, start=1)
        )
        return _table(rows, complete=True, reason=None)

    return evaluate


def _aggregate(window: MetricWindow, aggregation: MetricAggregation) -> float:
    values = [sample.value for sample in window.samples]
    if aggregation is MetricAggregation.COUNT:
        return float(len(values))
    if not values:
        return 0.0
    if aggregation is MetricAggregation.SUM:
        return math.fsum(values)
    if aggregation is MetricAggregation.AVERAGE:
        return math.fsum(values) / len(values)
    if aggregation is MetricAggregation.MINIMUM:
        return min(values)
    return max(values)


def _metric_display_samples(
    samples: tuple[MetricSample, ...],
) -> tuple[MetricSample, ...]:
    """Keep endpoints and each time bucket's value envelope within the display bound."""

    if len(samples) <= _MAX_SERIES_POINTS:
        return samples
    interior = samples[1:-1]
    bucket_count = (_MAX_SERIES_POINTS - 2) // 2
    selected: list[MetricSample] = [samples[0]]
    for index in range(bucket_count):
        start = len(interior) * index // bucket_count
        end = len(interior) * (index + 1) // bucket_count
        bucket = interior[start:end]
        minimum = min(bucket, key=lambda sample: (sample.value, sample.timestamp))
        maximum = max(bucket, key=lambda sample: (sample.value, sample.timestamp))
        for sample in sorted((minimum, maximum), key=lambda item: item.timestamp):
            if sample.timestamp != selected[-1].timestamp:
                selected.append(sample)
    selected.append(samples[-1])
    return tuple(selected)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _table(
    rows: tuple[QueryRow, ...],
    *,
    complete: bool,
    reason: str | None,
) -> dict[str, object]:
    table = QueryTable(rows=rows, complete=complete, truncation_reason=reason)
    return cast(dict[str, object], json.loads(table.canonical_json()))


__all__ = [
    "MAX_RESOURCE_METRIC_WINDOW_SECONDS",
    "RESOURCE_METRIC_FUNCTION_NAME",
    "RESOURCE_METRIC_SERIES_FUNCTION_NAME",
    "resource_metric_function_type",
    "resource_metric_inventory_function",
    "resource_metric_series_function",
    "resource_metric_series_function_type",
]
