"""Bounded gateway/backend metric evidence, without health or causal verdicts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

from .functions import ContextualOntologyFunction, FunctionInvocationContext
from .metric_semantics import (
    MetricAggregation,
    MetricSemanticDefinition,
    MetricSemanticRegistry,
    MetricWindow,
    MetricWindowProvider,
    compare_aligned_windows,
)
from .query_gateway import SecuredObjectSetQueryResult
from .query_values import QueryRow, QueryTable
from .resource_configuration_projection import project_resource_configuration

GATEWAY_DIAGNOSTIC_FUNCTION_NAME = "query.gateway_diagnostic_evidence"
GATEWAY_DIAGNOSTIC_OUTPUT_SHAPE = "gateway_diagnostic_evidence"
MAX_GATEWAY_BACKENDS = 4
MAX_GATEWAY_WINDOW_SECONDS = 86_400
MAX_GATEWAY_HISTORY_SECONDS = 7 * 86_400
MAX_GATEWAY_PROVIDER_READS = 74
MAX_GATEWAY_SAMPLES_PER_WINDOW = 1000
MAX_REQUESTED_BACKEND_CANDIDATES = 16
_MAX_CONCURRENCY = 4
_MAX_READ_SECONDS = 4.0
_MAX_TOTAL_SECONDS = 20.0
_TIME_FIELDS = ("baseline_start", "baseline_end", "current_start", "current_end")
_GATEWAY_PROFILES = MappingProxyType(
    {
        "network.application-gateway": (
            "gateway.total_time",
            "gateway.backend.connect_time",
            "gateway.backend.first_byte_time",
            "gateway.backend.last_byte_time",
            "gateway.backend.unhealthy_host_count",
            "gateway.response.5xx.count",
            "gateway.backend.response.5xx.count",
        ),
        "api-gateway": (
            "api_gateway.duration",
            "api_gateway.backend.duration",
            "api_gateway.request.count",
            "api_gateway.response.429.count",
            "api_gateway.response.500.count",
            "api_gateway.response.503.count",
            "api_gateway.backend.response.500.count",
            "api_gateway.backend.response.429.count",
            "api_gateway.backend.response.503.count",
        ),
    }
)
_MODEL_PROFILE = (
    "model.request.count",
    "model.response.429.count",
    "model.response.500.count",
    "model.response.503.count",
    "model.time_to_response",
    "model.time_to_last_byte",
    "model.token.count",
)
_BACKEND_PROFILES = MappingProxyType(
    {
        **_GATEWAY_PROFILES,
        "llm-model-deployment": _MODEL_PROFILE,
        "llm-endpoint": _MODEL_PROFILE,
        "compute.vm": ("resource.cpu.utilization_pct", "resource.memory.available_pct"),
        "compute.container-app": (
            "resource.saturation",
            "request.timeout",
            "resource.activation.failure",
        ),
    }
)
_PROFILE_EXCLUSIONS = {
    "network.application-gateway": ("gateway.backend.healthy_host_count",),
}


@dataclass(frozen=True, slots=True)
class GatewayBackendFilter:
    """An exact requested identity, not an authorization or relationship assertion."""

    field: str
    value: str

    def __post_init__(self) -> None:
        if (
            self.field not in {"id", "name", "model_name"}
            or not isinstance(self.value, str)
            or not self.value
            or self.value != self.value.strip()
            or len(self.value) > (256 if self.field == "model_name" else 512)
        ):
            raise ValueError("requested backend filter MUST be one bounded exact identity")

    @classmethod
    def from_value(cls, value: object) -> GatewayBackendFilter:
        if not isinstance(value, Mapping) or set(value) != {"field", "value"}:
            raise ValueError("requested backend filter fields are invalid")
        if not isinstance(value["field"], str) or not isinstance(value["value"], str):
            raise ValueError("requested backend identity MUST be text")
        return cls(field=value["field"], value=value["value"])

    def arguments(self) -> dict[str, str]:
        return {"field": self.field, "value": self.value}


@dataclass(frozen=True, slots=True)
class GatewayDiagnosticWindows:
    baseline_start: datetime
    baseline_end: datetime
    current_start: datetime
    current_end: datetime

    def __post_init__(self) -> None:
        if any(getattr(self, field).tzinfo is None for field in _TIME_FIELDS):
            raise ValueError("gateway windows MUST be timezone-aware")
        baseline = (self.baseline_end - self.baseline_start).total_seconds()
        current = (self.current_end - self.current_start).total_seconds()
        if (
            not 300 <= baseline == current <= MAX_GATEWAY_WINDOW_SECONDS
            or self.baseline_end > self.current_start
            or (self.current_end - self.baseline_start).total_seconds()
            > MAX_GATEWAY_HISTORY_SECONDS
        ):
            raise ValueError("gateway windows MUST be bounded, equal, and non-overlapping")

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, Any]) -> GatewayDiagnosticWindows:
        parsed: dict[str, datetime] = {}
        for field in _TIME_FIELDS:
            value = arguments[field]
            if not isinstance(value, str):
                raise ValueError("gateway window boundary MUST be timestamp text")
            boundary = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if boundary.tzinfo is None:
                raise ValueError("gateway window boundary MUST be timezone-aware")
            parsed[field] = boundary.astimezone(UTC)
        return cls(**parsed)

    def arguments(self) -> dict[str, str]:
        return {field: getattr(self, field).isoformat() for field in _TIME_FIELDS}


def gateway_diagnostic_windows(
    scope: Mapping[str, Any],
    *,
    evaluation_time: datetime,
) -> GatewayDiagnosticWindows:
    """Resolve only typed window fields; one server cutoff pins every target."""
    if evaluation_time.tzinfo is None:
        raise ValueError("gateway evaluation time MUST be timezone-aware")
    known_at = evaluation_time.astimezone(UTC)
    if not scope or set(scope) == {"window_seconds"}:
        seconds = scope.get("window_seconds", 900)
        if isinstance(seconds, bool) or not isinstance(seconds, int):
            raise ValueError("gateway duration MUST be integer seconds")
        duration = timedelta(seconds=seconds)
        result = GatewayDiagnosticWindows(
            known_at - duration * 2,
            known_at - duration,
            known_at - duration,
            known_at,
        )
    elif set(scope) == set(_TIME_FIELDS):
        result = GatewayDiagnosticWindows.from_arguments(scope)
    else:
        raise ValueError("gateway temporal scope contains unsupported fields")
    if (
        result.current_end > known_at
        or (known_at - result.baseline_start).total_seconds() > MAX_GATEWAY_HISTORY_SECONDS
    ):
        raise ValueError("gateway windows exceed the current knowledge boundary")
    return result


def gateway_diagnostic_function_type() -> OntologyFunctionType:
    return OntologyFunctionType(
        name=GATEWAY_DIAGNOSTIC_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query_result", "backend_query_result", *_TIME_FIELDS],
            "dependentRequired": {"requested_backend_query_result": ["requested_backend_filter"]},
            "properties": {
                **{
                    name: {"type": "object", "x-fdai-dependency-only": True}
                    for name in (
                        "query_result",
                        "backend_query_result",
                        "requested_backend_query_result",
                    )
                },
                "requested_backend_filter": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["field", "value"],
                    "properties": {
                        "field": {"type": "string", "enum": ["id", "name", "model_name"]},
                        "value": {"type": "string", "minLength": 1, "maxLength": 512},
                    },
                },
                **{name: {"type": "string", "format": "date-time"} for name in _TIME_FIELDS},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "properties": {
                "rows": {"type": "array", "maxItems": 40},
                "complete": {"type": "boolean"},
                "truncation_reason": {"type": ["string", "null"]},
            },
        },
        read_sets=["Resource"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=["operations-review"],
        timeout_seconds=25,
        cpu_millis=500,
        memory_bytes=67_108_864,
        max_output_bytes=262_144,
        network_allowed=False,
        credentials_allowed=False,
    )


@dataclass(frozen=True, slots=True)
class _Read:
    window: MetricWindow | None = None
    reason: str | None = None


def gateway_diagnostic_function(
    ontology_release: OntologyRelease,
    *,
    registry: MetricSemanticRegistry,
    provider: MetricWindowProvider,
    read_timeout_seconds: float = _MAX_READ_SECONDS,
    total_timeout_seconds: float = _MAX_TOTAL_SECONDS,
) -> ContextualOntologyFunction:
    """Reuse the injected metric seam; all targets come from issued Resource sets."""
    ontology_release.type_ref(OntologyDeclarationKind.FUNCTION, GATEWAY_DIAGNOSTIC_FUNCTION_NAME)
    if not (
        0 < read_timeout_seconds <= _MAX_READ_SECONDS
        and 0 < total_timeout_seconds <= _MAX_TOTAL_SECONDS
    ):
        raise ValueError("gateway diagnostic deadlines MUST retain the bounded maximum")
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def evaluate(
        arguments: Mapping[str, Any],
        context: FunctionInvocationContext,
    ) -> object:
        root = _authorized_scope(arguments["query_result"], context, ontology_release)
        backends = _authorized_scope(arguments["backend_query_result"], context, ontology_release)
        requested_filter = (
            GatewayBackendFilter.from_value(arguments["requested_backend_filter"])
            if "requested_backend_filter" in arguments
            else None
        )
        requested_scope = (
            _authorized_scope(
                arguments["requested_backend_query_result"], context, ontology_release
            )
            if "requested_backend_query_result" in arguments
            else None
        )
        if requested_scope is not None and requested_filter is None:
            raise ValueError("requested backend scope requires an explicit identity filter")
        known_at = root.materialization.definition.as_of
        windows = gateway_diagnostic_windows(
            {field: arguments[field] for field in _TIME_FIELDS},
            evaluation_time=known_at,
        )
        if backends.materialization.definition.as_of != known_at:
            raise ValueError("gateway and backend scope snapshots MUST match")
        if requested_scope is not None and (
            requested_scope.materialization.definition.as_of != known_at
            or abs((requested_scope.receipt.observation_cutoff - known_at).total_seconds()) > 5
        ):
            raise ValueError("requested backend scope MUST share the pinned current cutoff")
        if requested_filter is not None and any(
            abs((scope.receipt.observation_cutoff - known_at).total_seconds()) > 5
            for scope in (root, backends)
        ):
            raise ValueError("requested backend resolution requires current scope cutoffs")
        targets = root.materialization.graph.objects
        root_reason = _scope_reason(root)
        if root_reason or len(targets) != 1:
            reason = root_reason or (
                "gateway_not_found" if not targets else "gateway_identity_ambiguous"
            )
            return _result([], [reason], context, windows)
        target = targets[0]
        resource_type = _resource_type(target)
        profile = _GATEWAY_PROFILES.get(resource_type)
        if profile is None:
            return _result([], ["gateway_resource_type_unsupported"], context, windows)

        selected: list[tuple[str, OntologyObjectRecord, tuple[str, ...]]] = [
            ("gateway", target, profile),
        ]
        reasons: list[str] = []
        backend_objects = backends.materialization.graph.objects
        backend_reason = _scope_reason(backends)
        selection: dict[str, object] = {}
        if requested_filter is not None:
            matched, role, selection_reasons = _select_requested_backend(
                requested_filter,
                root,
                backends,
                requested_scope,
            )
            reasons.extend(selection_reasons)
            selection = {
                "requested_backend_field": requested_filter.field,
                "requested_backend_value": requested_filter.value,
                "requested_backend_relationship_unverified": role != "backend",
                "requested_backend_configuration_status": "not_collected_for_filtered_selection",
                "requested_backend_resolution_scope": (
                    "observed_path_then_requested_scope"
                    if requested_scope is not None
                    else "observed_path_only"
                ),
            }
            if matched is not None:
                concepts = _BACKEND_PROFILES.get(_resource_type(matched), ())
                if not concepts:
                    reasons.append("backend_metric_profile_unsupported")
                selected.append((role, matched, concepts))
        elif backend_reason:
            reasons.append(f"backend_{backend_reason}")
        elif len(backend_objects) > MAX_GATEWAY_BACKENDS:
            reasons.append("backend_resource_limit_exceeded")
        elif not backend_objects:
            reasons.append("no_observed_routes_to_relationship")
            if resource_type == "api-gateway":
                reasons.append("api_gateway_backend_mapping_unresolved")
        elif root.receipt.source_generation != backends.receipt.source_generation:
            reasons.append("backend_snapshot_generation_mismatch")
        elif any(item.id == target.id for item in backend_objects):
            reasons.append("backend_scope_contains_gateway")
        else:
            for backend in sorted(backend_objects, key=lambda item: item.id):
                backend_profile = _BACKEND_PROFILES.get(_resource_type(backend))
                if backend_profile is None:
                    reasons.append("backend_metric_profile_unsupported")
                    selected.append(("backend", backend, ()))
                else:
                    selected.append(("backend", backend, backend_profile))

        jobs: dict[tuple[str, str, str], asyncio.Task[_Read]] = {}
        definitions: dict[str, MetricSemanticDefinition] = {}
        for _role, resource, concepts in selected:
            for concept in concepts:
                if concept not in registry.definitions:
                    continue
                definition = registry.resolve(concept)
                definitions[concept] = definition
                for period, start, end in (
                    ("baseline", windows.baseline_start, windows.baseline_end),
                    ("current", windows.current_start, windows.current_end),
                ):
                    jobs[(resource.id, concept, period)] = asyncio.create_task(
                        _read_window(
                            provider,
                            semaphore,
                            definition,
                            resource.id,
                            start,
                            end,
                            timeout_seconds=read_timeout_seconds,
                        )
                    )
        if len(jobs) > MAX_GATEWAY_PROVIDER_READS:
            for task in jobs.values():
                task.cancel()
            await asyncio.gather(*jobs.values(), return_exceptions=True)
            raise ValueError("gateway profile exceeds the fixed provider-read bound")
        reads: dict[tuple[str, str, str], _Read] = {}
        try:
            if jobs:
                await asyncio.wait(tuple(jobs.values()), timeout=total_timeout_seconds)
        finally:
            for task in jobs.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*jobs.values(), return_exceptions=True)
        for key, task in jobs.items():
            reads[key] = (
                _Read(reason="diagnostic_deadline_exceeded") if task.cancelled() else task.result()
            )
        rows: list[QueryRow] = []
        for role, resource, concepts in selected:
            if not concepts:
                rows.append(
                    QueryRow.from_values(
                        f"unsupported-{len(rows)}",
                        {
                            "row_kind": "metric_gap",
                            "resource_id": resource.id,
                            "resource_type": _resource_type(resource),
                            "role": role,
                            "relationship_unverified": role == "requested_comparison",
                            "reason": "backend_metric_profile_unsupported",
                            "execution_authority": False,
                            "cause_claim_supported": False,
                        },
                    )
                )
            for concept in concepts:
                baseline = reads.get(
                    (resource.id, concept, "baseline"),
                    _Read(reason="metric_concept_unavailable"),
                )
                current = reads.get(
                    (resource.id, concept, "current"),
                    _Read(reason="metric_concept_unavailable"),
                )
                values = _comparison_row(
                    role,
                    resource,
                    concept,
                    definitions.get(concept),
                    baseline,
                    current,
                    windows,
                )
                if values["reason"] is not None:
                    reasons.append(str(values["reason"]))
                rows.append(QueryRow.from_values(f"gateway-metric-{len(rows):02d}", values))
        return _result(
            rows,
            reasons,
            context,
            windows,
            scope={
                "gateway_resource_id": target.id,
                "gateway_resource_type": resource_type,
                "relationship_snapshot_at": known_at.isoformat(),
                "observed_backend_count": len(backend_objects),
                "selected_backend_count": sum(role == "backend" for role, _, _ in selected),
                "requested_comparison_count": sum(
                    role == "requested_comparison" for role, _, _ in selected
                ),
                "scheduled_provider_read_count": len(jobs),
                "profile_excluded_concepts": list(_PROFILE_EXCLUSIONS.get(resource_type, ())),
                **selection,
            },
        )

    return evaluate


def _authorized_scope(
    value: object,
    context: FunctionInvocationContext,
    release: OntologyRelease,
) -> SecuredObjectSetQueryResult:
    secured = SecuredObjectSetQueryResult.model_validate(value)
    if (
        context.purposes != ("operations-review",)
        or context.caller_agent != "Bragi"
        or secured.receipt.purpose != "operations-review"
        or secured.receipt.caller_role != context.caller_role
        or secured.receipt.ontology_release != release.ref()
        or secured.receipt.projected_result_digest not in context.evidence_refs
    ):
        raise PermissionError("gateway diagnostics require issued operations-review scopes")
    return secured


def _scope_reason(secured: SecuredObjectSetQueryResult) -> str | None:
    if not secured.receipt.complete or secured.receipt.truncated:
        return "resource_scope_incomplete"
    if (
        secured.receipt.redactions.redacted_identity_count
        or secured.receipt.redactions.removed_link_count
    ):
        return "resource_scope_redacted"
    objects = secured.materialization.graph.objects
    if any(item.object_type != "Resource" for item in objects):
        return "resource_scope_type_mismatch"
    if len({item.id for item in objects}) != len(objects):
        return "resource_scope_duplicate_identity"
    return None


def _resource_type(resource: OntologyObjectRecord) -> str:
    value = resource.properties.get("type")
    return value if isinstance(value, str) else ""


def _select_requested_backend(
    requested: GatewayBackendFilter,
    root: SecuredObjectSetQueryResult,
    observed: SecuredObjectSetQueryResult,
    fallback: SecuredObjectSetQueryResult | None,
) -> tuple[OntologyObjectRecord | None, str, list[str]]:
    """A separate requested resource never establishes an unobserved routes_to edge."""
    reasons: list[str] = []
    absence_known = False
    objects = observed.materialization.graph.objects
    scope_reason = _scope_reason(observed)
    if scope_reason:
        reasons.append(f"backend_{scope_reason}")
    elif not objects:
        absence_known = True
        reasons.append("no_observed_routes_to_relationship")
        if _resource_type(root.materialization.graph.objects[0]) == "api-gateway":
            reasons.append("api_gateway_backend_mapping_unresolved")
    elif root.receipt.source_generation != observed.receipt.source_generation:
        reasons.append("backend_snapshot_generation_mismatch")
    elif len(objects) > MAX_GATEWAY_BACKENDS + 1:
        reasons.append("backend_resource_limit_exceeded")
    else:
        match, reason = _unique_backend_match(requested, objects)
        if reason is not None and reason != "requested_backend_not_found":
            return None, "unresolved", [reason]
        if match is not None:
            if match.id == root.materialization.graph.objects[0].id:
                return None, "unresolved", ["requested_backend_is_gateway"]
            return match, "backend", []
        reasons.append("requested_backend_not_in_observed_path")
        absence_known = True
    if fallback is None:
        reason = "requested_backend_not_found" if absence_known else "requested_backend_unresolved"
        return None, "unresolved", [*reasons, reason]
    reason = _scope_reason(fallback)
    if reason is not None:
        return None, "unresolved", [*reasons, f"requested_backend_{reason}"]
    candidates = fallback.materialization.graph.objects
    maximum = MAX_REQUESTED_BACKEND_CANDIDATES if requested.field == "model_name" else 2
    if len(candidates) > maximum:
        return None, "unresolved", [*reasons, "requested_backend_resource_limit_exceeded"]
    if candidates and root.receipt.source_generation != fallback.receipt.source_generation:
        return None, "unresolved", [*reasons, "requested_backend_snapshot_generation_mismatch"]
    match, reason = _unique_backend_match(requested, candidates)
    if match is None:
        return None, "unresolved", [*reasons, reason or "requested_backend_not_found"]
    if match.id == root.materialization.graph.objects[0].id:
        return None, "unresolved", [*reasons, "requested_backend_is_gateway"]
    return match, "requested_comparison", [*reasons, "relationship_unverified"]


def _unique_backend_match(
    requested: GatewayBackendFilter,
    objects: tuple[OntologyObjectRecord, ...],
) -> tuple[OntologyObjectRecord | None, str | None]:
    matches: list[OntologyObjectRecord] = []
    unknown = False
    for resource in objects:
        if requested.field == "id":
            value: object = resource.id
        elif requested.field == "name":
            value = resource.properties.get("name")
        else:
            resource_type = _resource_type(resource)
            if resource_type in {"", "<redacted>"}:
                unknown = True
                continue
            if resource_type != "llm-model-deployment":
                continue
            value = project_resource_configuration(resource).values["model_name"]
        if not isinstance(value, str) or not value or value == "<redacted>":
            unknown = True
        elif value == requested.value:
            matches.append(resource)
    if len(matches) > 1:
        return None, "requested_backend_ambiguous"
    if unknown:
        return None, "requested_backend_identity_unavailable"
    if not matches:
        return None, "requested_backend_not_found"
    return matches[0], None


async def _read_window(
    provider: MetricWindowProvider,
    semaphore: asyncio.Semaphore,
    definition: MetricSemanticDefinition,
    resource_id: str,
    start: datetime,
    end: datetime,
    *,
    timeout_seconds: float,
) -> _Read:
    try:
        async with semaphore, asyncio.timeout(timeout_seconds):
            window = await provider.read(
                definition=definition,
                resource_id=resource_id,
                start=start,
                end=end,
            )
    except TimeoutError:
        return _Read(reason="metric_read_timeout")
    except Exception:
        return _Read(reason="metric_provider_unavailable")
    if (
        not isinstance(window, MetricWindow)
        or window.resource_id != resource_id
        or window.concept_id != definition.concept_id
        or window.unit != definition.canonical_unit
        or window.start != start
        or window.end != end
    ):
        return _Read(reason="metric_scope_mismatch")
    if len(window.samples) > MAX_GATEWAY_SAMPLES_PER_WINDOW:
        return _Read(reason="metric_sample_limit_exceeded")
    if not window.complete:
        return _Read(window, "metric_window_incomplete")
    if not window.samples:
        return _Read(window, "metric_samples_missing")
    return _Read(window)


def _comparison_row(
    role: str,
    resource: OntologyObjectRecord,
    concept: str,
    definition: MetricSemanticDefinition | None,
    baseline: _Read,
    current: _Read,
    windows: GatewayDiagnosticWindows,
) -> dict[str, Any]:
    reason = baseline.reason or current.reason
    values: dict[str, Any] = {
        "row_kind": "metric_comparison",
        "resource_id": resource.id,
        "resource_type": _resource_type(resource),
        "role": role,
        "metric_concept": concept,
        "relationship_unverified": role == "requested_comparison",
        "unit": definition.canonical_unit if definition else None,
        "aggregation": definition.aggregation.value if definition else None,
        **windows.arguments(),
        "baseline_sample_count": len(baseline.window.samples) if baseline.window else None,
        "current_sample_count": len(current.window.samples) if current.window else None,
        "baseline_value": _observed_value(baseline, definition),
        "current_value": _observed_value(current, definition),
        "absolute_change": None,
        "relative_change": None,
        "trend": "unknown",
        "reason": reason,
        "comparison_complete": False,
        "baseline_missing_reason": baseline.reason,
        "current_missing_reason": current.reason,
        "evidence_refs": list(
            dict.fromkeys(
                ref
                for read in (baseline, current)
                if read.window
                for ref in read.window.evidence_refs
            )
        ),
        "execution_authority": False,
        "cause_claim_supported": False,
    }
    if (
        reason is not None
        or baseline.window is None
        or current.window is None
        or definition is None
    ):
        return values
    try:
        comparison = compare_aligned_windows(
            baseline.window,
            current.window,
            aggregation=definition.aggregation,
        )
        measured = (
            comparison.baseline_value,
            comparison.current_value,
            comparison.absolute_change,
            comparison.relative_change,
        )
        if any(value is not None and not math.isfinite(value) for value in measured):
            raise ValueError("non-finite metric comparison")
    except (ValueError, OverflowError):
        values["reason"] = "metric_comparison_unavailable"
        return values
    values.update(
        {
            "comparison_complete": True,
            "baseline_value": comparison.baseline_value,
            "current_value": comparison.current_value,
            "absolute_change": comparison.absolute_change,
            "relative_change": comparison.relative_change,
            "trend": (
                "increased"
                if cast(float, comparison.absolute_change) > 0
                else "decreased"
                if cast(float, comparison.absolute_change) < 0
                else "unchanged_observed_value"
            ),
        }
    )
    return values


def _observed_value(read: _Read, definition: MetricSemanticDefinition | None) -> float | None:
    if read.reason or read.window is None or definition is None:
        return None
    values = tuple(sample.value for sample in read.window.samples)
    if not values:
        return None
    try:
        if definition.aggregation is MetricAggregation.COUNT:
            value = float(len(values))
        elif definition.aggregation is MetricAggregation.MINIMUM:
            value = min(values)
        elif definition.aggregation is MetricAggregation.MAXIMUM:
            value = max(values)
        else:
            value = math.fsum(values)
            if definition.aggregation is MetricAggregation.AVERAGE:
                value /= len(values)
    except OverflowError:
        return None
    return value if math.isfinite(value) else None


def _result(
    rows: list[QueryRow],
    reasons: list[str],
    context: FunctionInvocationContext,
    windows: GatewayDiagnosticWindows,
    *,
    scope: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    reason = "+".join(sorted(set(reasons))) or None
    summary = QueryRow.from_values(
        "gateway-diagnostic-scope",
        {
            "row_kind": "diagnostic_scope",
            **(scope or {}),
            **windows.arguments(),
            "status": "evidence_incomplete" if reason else "bounded_profile_observed",
            "reason": reason,
            "coverage": "reviewed_metric_profile_only",
            "max_samples_per_window": MAX_GATEWAY_SAMPLES_PER_WINDOW,
            "interpretation_limits": (
                "Total duration includes backend time; status counts do not prove policy or cause; "
                "tokens measure consumption, not capacity; current routes do not prove historical "
                "routing. Available configuration facts are separate scoped comparison outputs. "
                "The compiler follows only one outgoing routes_to hop."
            ),
            "evidence_refs": list(context.evidence_refs),
            "execution_authority": False,
            "cause_claim_supported": False,
        },
    )
    return cast(
        dict[str, Any],
        json.loads(
            QueryTable(
                rows=(summary, *rows),
                complete=reason is None,
                truncation_reason=reason,
            ).canonical_json()
        ),
    )
