"""Exact-target request-error and activity correlation tests."""

from __future__ import annotations

import json

from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.core.ontology_platform.resource_error_activity_correlation_queries import (
    ERROR_ACTIVITY_CORRELATION_FUNCTION_NAME,
    error_activity_correlation_function,
    error_activity_correlation_function_type,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release


def _activity(*, rows: int = 0, complete: bool = True) -> dict[str, object]:
    table = QueryTable(
        rows=tuple(
            QueryRow.from_values(f"activity-{index}", {"operation": "write"})
            for index in range(rows)
        ),
        complete=complete,
        truncation_reason=None if complete else "activity_provider_unavailable",
    )
    return json.loads(table.canonical_json())


def _window(
    *,
    start: str,
    end: str,
    values: tuple[float, ...],
    complete: bool = True,
) -> dict[str, object]:
    return {
        "concept_id": "request.errors",
        "resource_id": "resource-a",
        "unit": "count",
        "start": start,
        "end": end,
        "samples": [{"timestamp": start, "value": value} for value in values],
        "complete": complete,
        "evidence_refs": [f"metric:{start}"],
        "missing_reason": None if complete else "metric_provider_unavailable",
    }


async def _invoke(
    *,
    baseline_values: tuple[float, ...],
    current_values: tuple[float, ...],
    activity_rows: int = 0,
    activity_complete: bool = True,
    current_complete: bool = True,
) -> dict[str, object]:
    declaration = error_activity_correlation_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(declaration, error_activity_correlation_function(release))
    result = await registry.invoke(
        ERROR_ACTIVITY_CORRELATION_FUNCTION_NAME,
        {
            "baseline_errors": _window(
                start="2026-08-20T23:10:00Z",
                end="2026-08-20T23:40:00Z",
                values=baseline_values,
            ),
            "current_errors": _window(
                start="2026-08-20T23:40:00Z",
                end="2026-08-21T00:10:00Z",
                values=current_values,
                complete=current_complete,
            ),
            "activity": _activity(rows=activity_rows, complete=activity_complete),
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )
    assert isinstance(result, dict)
    return result


async def test_correlation_reports_cooccurrence_without_claiming_causation() -> None:
    result = await _invoke(
        baseline_values=(1.0,),
        current_values=(3.0,),
        activity_rows=1,
    )

    assert result["complete"] is True
    values = result["rows"][0]["values"]
    assert values["error_trend"] == "increased"
    assert values["baseline_error_total"] == 1.0
    assert values["current_error_total"] == 3.0
    assert values["activity_state"] == "changes_observed"
    assert values["correlation_assessment"] == "cooccurrence_observed_not_causation"
    assert values["causal_claim_supported"] is False
    assert values["execution_authority"] is False


async def test_correlation_preserves_observed_zero_without_inventing_change() -> None:
    result = await _invoke(
        baseline_values=(0.0,),
        current_values=(0.0,),
    )

    assert result["complete"] is True
    values = result["rows"][0]["values"]
    assert values["error_trend"] == "unchanged"
    assert values["activity_state"] == "zero_changes_observed"
    assert values["correlation_assessment"] == "no_correlated_change_observed"


async def test_correlation_keeps_missing_metric_evidence_unproven() -> None:
    result = await _invoke(
        baseline_values=(0.0,),
        current_values=(),
        current_complete=False,
    )

    assert result["complete"] is False
    assert result["truncation_reason"] == "correlation_evidence_incomplete"
    values = result["rows"][0]["values"]
    assert values["error_trend"] == "unavailable"
    assert values["current_error_total"] is None
    assert values["correlation_assessment"] == "unproven_missing_evidence"
    assert "metric_provider_unavailable" in values["evidence_gaps"]
