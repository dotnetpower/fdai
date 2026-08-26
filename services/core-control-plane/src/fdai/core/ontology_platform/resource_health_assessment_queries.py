"""Deterministically assess exact-target health evidence without inferring readiness."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from fdai.core.ontology_platform.functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
)
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

TARGET_HEALTH_ASSESSMENT_FUNCTION_NAME = "query.target_health_assessment"
_INPUT_NAMES = (
    "current_state",
    "activity",
    "resource_saturation",
    "request_volume",
    "request_errors",
)


def target_health_assessment_function_type() -> OntologyFunctionType:
    """Return the fixed declaration for the no-authority health evidence reducer."""

    return OntologyFunctionType(
        name=TARGET_HEALTH_ASSESSMENT_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": list(_INPUT_NAMES),
            "properties": {
                name: {"type": "object", "x-fdai-dependency-only": True} for name in _INPUT_NAMES
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "properties": {
                "rows": {"type": "array", "maxItems": 1},
                "complete": {"type": "boolean"},
                "truncation_reason": {"type": ["string", "null"]},
            },
        },
        read_sets=["Resource"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=["operations-review"],
        timeout_seconds=5,
        cpu_millis=100,
        memory_bytes=33_554_432,
        max_output_bytes=32_768,
        network_allowed=False,
        credentials_allowed=False,
    )


def target_health_assessment_function(
    ontology_release: OntologyRelease,
) -> ContextualOntologyFunction:
    """Reduce current-state, activity, and metrics into an evidence-sufficiency answer."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        TARGET_HEALTH_ASSESSMENT_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("target health purpose does not match invocation context")
        current_state = _query_table(arguments["current_state"], "current_state")
        activity = _query_table(arguments["activity"], "activity")
        saturation = _metric_window(arguments["resource_saturation"], "resource.saturation")
        request_volume = _metric_window(arguments["request_volume"], "request.volume")
        request_errors = _metric_window(arguments["request_errors"], "request.errors")
        current_values = current_state.rows[0].values if len(current_state.rows) == 1 else {}
        gaps = _gaps(
            current_state=current_state,
            activity=activity,
            saturation=saturation,
            request_volume=request_volume,
            request_errors=request_errors,
            current_values=current_values,
        )
        saturation_values = _sample_values(saturation)
        request_values = _sample_values(request_volume)
        error_values = _sample_values(request_errors)
        request_total = sum(request_values) if request_values else None
        values = {
            "target": current_values.get("name"),
            "overall_assessment": "insufficient_evidence",
            "evidence_sufficient": False,
            "platform_lifecycle": _lifecycle_assessment(current_values),
            "readiness": "not_proven",
            "application_service_health": "not_proven",
            "stability": (
                "control_plane_activity_observed"
                if activity.rows
                else "process_stability_not_proven"
            ),
            "resource_pressure": (
                "cpu_observed_capacity_unknown" if saturation_values else "not_proven"
            ),
            "request_telemetry": (
                "zero_observed_requests_not_health_proof"
                if request_total == 0
                else "request_samples_observed"
                if request_total is not None
                else "not_proven"
            ),
            "cpu_sample_count": len(saturation_values),
            "cpu_average_nanocores": _average(saturation_values),
            "cpu_max_nanocores": max(saturation_values) if saturation_values else None,
            "request_total": request_total,
            "request_error_total": sum(error_values) if error_values else None,
            "source_observed_at": current_values.get("source_observed_at"),
            "inventory_read_at": current_values.get("inventory_read_at"),
            "metric_window_end": saturation.get("end"),
            "evidence_gaps": ", ".join(gaps),
            "execution_authority": False,
        }
        table = QueryTable(
            rows=(QueryRow.from_values("target-health-assessment", values),),
            complete=False,
            truncation_reason="health_claim_evidence_incomplete",
        )
        return cast(dict[str, object], json.loads(table.canonical_json()))

    return evaluate


def _query_table(value: object, field: str) -> QueryTable:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} MUST be a query table")
    raw_rows = value.get("rows")
    complete = value.get("complete")
    reason = value.get("truncation_reason")
    if (
        not isinstance(raw_rows, list)
        or not isinstance(complete, bool)
        or (reason is not None and not isinstance(reason, str))
    ):
        raise ValueError(f"{field} query table is invalid")
    rows: list[QueryRow] = []
    for item in raw_rows:
        if not isinstance(item, Mapping):
            raise ValueError(f"{field} query row is invalid")
        row_id = item.get("row_id")
        values = item.get("values")
        if not isinstance(row_id, str) or not isinstance(values, Mapping):
            raise ValueError(f"{field} query row is invalid")
        rows.append(QueryRow.from_values(row_id, values))
    return QueryTable(rows=tuple(rows), complete=complete, truncation_reason=reason)


def _metric_window(value: object, concept_id: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or value.get("concept_id") != concept_id:
        raise ValueError(f"{concept_id} metric window is invalid")
    if not isinstance(value.get("complete"), bool):
        raise ValueError(f"{concept_id} metric completeness is invalid")
    if not isinstance(value.get("samples"), list):
        raise ValueError(f"{concept_id} metric samples are invalid")
    return value


def _sample_values(window: Mapping[str, Any]) -> tuple[float, ...]:
    raw = window.get("samples")
    if not isinstance(raw, list):
        return ()
    values: list[float] = []
    for sample in raw:
        if not isinstance(sample, Mapping):
            return ()
        value = sample.get("value")
        if not isinstance(value, int | float) or isinstance(value, bool):
            return ()
        converted = float(value)
        if not math.isfinite(converted):
            return ()
        values.append(converted)
    return tuple(values)


def _lifecycle_assessment(values: Mapping[str, Any]) -> str:
    provisioning = values.get("provisioning_status")
    running = values.get("running_status")
    if provisioning == "Succeeded" and running == "Running":
        return "observed_running"
    if provisioning is not None or running is not None:
        return "observed_not_running"
    return "not_proven"


def _gaps(
    *,
    current_state: QueryTable,
    activity: QueryTable,
    saturation: Mapping[str, Any],
    request_volume: Mapping[str, Any],
    request_errors: Mapping[str, Any],
    current_values: Mapping[str, Any],
) -> tuple[str, ...]:
    gaps = [
        "live_replica_readiness_unavailable",
        "process_restart_count_unavailable",
        "application_work_success_unavailable",
        "dependency_health_unavailable",
        "memory_metric_unavailable",
        "runtime_logs_unavailable",
    ]
    if not current_state.complete:
        gaps.append(current_state.truncation_reason or "current_state_incomplete")
    if not activity.complete:
        gaps.append(activity.truncation_reason or "activity_incomplete")
    if current_values.get("source_observed_at") is None:
        gaps.append("source_observation_time_unavailable")
    for window in (saturation, request_volume, request_errors):
        if window.get("complete") is not True:
            reason = window.get("missing_reason")
            gaps.append(str(reason) if reason else "metric_window_incomplete")
    return tuple(dict.fromkeys(gaps))


def _average(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


__all__ = [
    "TARGET_HEALTH_ASSESSMENT_FUNCTION_NAME",
    "target_health_assessment_function",
    "target_health_assessment_function_type",
]
