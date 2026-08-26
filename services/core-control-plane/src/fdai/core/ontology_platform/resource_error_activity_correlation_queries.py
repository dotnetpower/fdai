"""Deterministically correlate request-error windows with bounded change activity."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime
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

ERROR_ACTIVITY_CORRELATION_FUNCTION_NAME = "query.resource_error_activity_correlation"
_INPUT_NAMES = ("baseline_errors", "current_errors", "activity")


def error_activity_correlation_function_type() -> OntologyFunctionType:
    """Return the fixed read-only declaration for error/activity correlation."""

    return OntologyFunctionType(
        name=ERROR_ACTIVITY_CORRELATION_FUNCTION_NAME,
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


def error_activity_correlation_function(
    ontology_release: OntologyRelease,
) -> ContextualOntologyFunction:
    """Reduce aligned request-error windows and activity into a no-cause assessment."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        ERROR_ACTIVITY_CORRELATION_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("error activity purpose does not match invocation context")
        baseline = _metric_window(arguments["baseline_errors"])
        current = _metric_window(arguments["current_errors"])
        activity = _query_table(arguments["activity"])
        _verify_aligned_windows(baseline, current)
        baseline_total = _sample_total(baseline)
        current_total = _sample_total(current)
        error_trend = _error_trend(
            baseline=baseline,
            current=current,
            baseline_total=baseline_total,
            current_total=current_total,
        )
        activity_state = (
            "unavailable"
            if not activity.complete
            else "changes_observed"
            if activity.rows
            else "zero_changes_observed"
        )
        complete = (
            baseline.get("complete") is True
            and current.get("complete") is True
            and baseline_total is not None
            and current_total is not None
            and activity.complete
        )
        gaps = _evidence_gaps(
            baseline=baseline,
            current=current,
            activity=activity,
            baseline_total=baseline_total,
            current_total=current_total,
        )
        values = {
            "error_trend": error_trend,
            "baseline_error_total": baseline_total,
            "current_error_total": current_total,
            "absolute_error_change": (
                current_total - baseline_total
                if baseline_total is not None and current_total is not None
                else None
            ),
            "baseline_window_start": baseline.get("start"),
            "baseline_window_end": baseline.get("end"),
            "current_window_start": current.get("start"),
            "current_window_end": current.get("end"),
            "activity_state": activity_state,
            "activity_change_count": len(activity.rows) if activity.complete else None,
            "correlation_assessment": _correlation_assessment(
                complete=complete,
                error_trend=error_trend,
                activity=activity,
            ),
            "causal_claim_supported": False,
            "evidence_gaps": ", ".join(gaps),
            "execution_authority": False,
        }
        table = QueryTable(
            rows=(QueryRow.from_values("target-error-activity-correlation", values),),
            complete=complete,
            truncation_reason=None if complete else "correlation_evidence_incomplete",
        )
        return cast(dict[str, object], json.loads(table.canonical_json()))

    return evaluate


def _metric_window(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or value.get("concept_id") != "request.errors":
        raise ValueError("request.errors metric window is invalid")
    if (
        not isinstance(value.get("resource_id"), str)
        or not isinstance(value.get("unit"), str)
        or not isinstance(value.get("start"), str)
        or not isinstance(value.get("end"), str)
        or not isinstance(value.get("complete"), bool)
        or not isinstance(value.get("samples"), list)
    ):
        raise ValueError("request.errors metric window evidence is invalid")
    return value


def _query_table(value: object) -> QueryTable:
    if not isinstance(value, Mapping):
        raise ValueError("activity MUST be a query table")
    raw_rows = value.get("rows")
    complete = value.get("complete")
    reason = value.get("truncation_reason")
    if (
        not isinstance(raw_rows, list)
        or not isinstance(complete, bool)
        or (reason is not None and not isinstance(reason, str))
    ):
        raise ValueError("activity query table is invalid")
    rows: list[QueryRow] = []
    for item in raw_rows:
        if not isinstance(item, Mapping):
            raise ValueError("activity query row is invalid")
        row_id = item.get("row_id")
        values = item.get("values")
        if not isinstance(row_id, str) or not isinstance(values, Mapping):
            raise ValueError("activity query row is invalid")
        rows.append(QueryRow.from_values(row_id, values))
    return QueryTable(rows=tuple(rows), complete=complete, truncation_reason=reason)


def _verify_aligned_windows(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
) -> None:
    if baseline.get("resource_id") != current.get("resource_id"):
        raise ValueError("request error windows MUST target the same resource")
    if baseline.get("unit") != current.get("unit"):
        raise ValueError("request error windows MUST use the same unit")
    if baseline.get("end") != current.get("start"):
        raise ValueError("request error windows MUST be contiguous")
    baseline_start = _timestamp(baseline["start"])
    baseline_end = _timestamp(baseline["end"])
    current_start = _timestamp(current["start"])
    current_end = _timestamp(current["end"])
    if (
        baseline_start >= baseline_end
        or current_start >= current_end
        or baseline_end - baseline_start != current_end - current_start
    ):
        raise ValueError("request error windows MUST have equal positive duration")


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("request error window timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("request error window timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("request error window timestamp MUST include a timezone")
    return parsed


def _sample_total(window: Mapping[str, Any]) -> float | None:
    samples = window.get("samples")
    if not isinstance(samples, list) or not samples:
        return None
    total = 0.0
    for sample in samples:
        if not isinstance(sample, Mapping):
            return None
        value = sample.get("value")
        if not isinstance(value, int | float) or isinstance(value, bool):
            return None
        converted = float(value)
        if not math.isfinite(converted):
            return None
        total += converted
    return total


def _error_trend(
    *,
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    baseline_total: float | None,
    current_total: float | None,
) -> str:
    if (
        baseline.get("complete") is not True
        or current.get("complete") is not True
        or baseline_total is None
        or current_total is None
    ):
        return "unavailable"
    if current_total > baseline_total:
        return "increased"
    if current_total < baseline_total:
        return "decreased"
    return "unchanged"


def _correlation_assessment(
    *,
    complete: bool,
    error_trend: str,
    activity: QueryTable,
) -> str:
    if not complete:
        return "unproven_missing_evidence"
    if error_trend == "increased" and activity.rows:
        return "cooccurrence_observed_not_causation"
    return "no_correlated_change_observed"


def _evidence_gaps(
    *,
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    activity: QueryTable,
    baseline_total: float | None,
    current_total: float | None,
) -> tuple[str, ...]:
    gaps: list[str] = []
    for name, window, total in (
        ("baseline", baseline, baseline_total),
        ("current", current, current_total),
    ):
        if window.get("complete") is not True:
            gaps.append(str(window.get("missing_reason") or f"{name}_errors_incomplete"))
        elif total is None:
            gaps.append(f"{name}_errors_unobserved")
    if not activity.complete:
        gaps.append(activity.truncation_reason or "activity_incomplete")
    return tuple(dict.fromkeys(gaps))


__all__ = [
    "ERROR_ACTIVITY_CORRELATION_FUNCTION_NAME",
    "error_activity_correlation_function",
    "error_activity_correlation_function_type",
]
