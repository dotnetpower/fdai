"""MySQL pressure evidence reducer tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.detection.series import MetricSample
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.metric_semantics import CausalJoinStatus, MetricWindow
from fdai.core.ontology_platform.mysql_pressure_evidence import (
    MYSQL_DEMAND_BUNDLE_FUNCTION_NAME,
    MYSQL_PRESSURE_CONCEPTS,
    MYSQL_PRESSURE_FUNCTION_NAME,
    MYSQL_SATURATION_BUNDLE_FUNCTION_NAME,
    assess_mysql_pressure_evidence,
    mysql_demand_bundle_function,
    mysql_demand_bundle_function_type,
    mysql_pressure_function,
    mysql_pressure_function_type,
    mysql_saturation_bundle_function,
    mysql_saturation_bundle_function_type,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release

NOW = datetime(2026, 8, 26, 6, 0, tzinfo=UTC)


def _pair(
    concept_id: str,
    baseline: float,
    current: float,
    *,
    complete: bool = True,
) -> tuple[MetricWindow, MetricWindow]:
    baseline_start = NOW - timedelta(minutes=20)
    baseline_end = NOW - timedelta(minutes=10)
    current_start = NOW - timedelta(minutes=10)
    unit = "ms" if concept_id == "dependency.latency" else "count"
    if concept_id.endswith("utilization_pct"):
        unit = "percent"
    return (
        MetricWindow(
            concept_id=concept_id,
            resource_id="resource-mysql-example",
            unit=unit,
            start=baseline_start,
            end=baseline_end,
            samples=(MetricSample(timestamp=baseline_end, value=baseline),),
            complete=complete,
            missing_reason=None if complete else "provider_gap",
            evidence_refs=(f"baseline:{concept_id}",),
        ),
        MetricWindow(
            concept_id=concept_id,
            resource_id="resource-mysql-example",
            unit=unit,
            start=current_start,
            end=NOW,
            samples=(MetricSample(timestamp=NOW, value=current),),
            complete=complete,
            missing_reason=None if complete else "provider_gap",
            evidence_refs=(f"current:{concept_id}",),
        ),
    )


def _windows(**changes: tuple[float, float]) -> dict[str, tuple[MetricWindow, MetricWindow]]:
    defaults = {
        "database.mysql.active_connections": (20.0, 20.0),
        "database.mysql.cpu.utilization_pct": (40.0, 40.0),
        "database.mysql.query.count": (100.0, 100.0),
        "database.mysql.slow_query.count": (1.0, 1.0),
        "dependency.latency": (20.0, 80.0),
    }
    defaults.update(changes)
    return {concept_id: _pair(concept_id, *values) for concept_id, values in defaults.items()}


def test_reducer_supports_saturation_and_refutes_request_growth() -> None:
    result = assess_mysql_pressure_evidence(
        _windows(
            **{
                "database.mysql.cpu.utilization_pct": (40.0, 90.0),
                "database.mysql.slow_query.count": (1.0, 12.0),
            }
        )
    )

    assert result.mysql_saturation_status is CausalJoinStatus.SUPPORTED
    assert result.request_growth_status is CausalJoinStatus.REFUTED
    assert result.complete is True
    assert result.cause_claim_supported is False
    assert result.execution_authority is False


def test_reducer_supports_request_growth_and_refutes_saturation() -> None:
    result = assess_mysql_pressure_evidence(
        _windows(**{"database.mysql.query.count": (100.0, 500.0)})
    )

    assert result.mysql_saturation_status is CausalJoinStatus.REFUTED
    assert result.request_growth_status is CausalJoinStatus.SUPPORTED


def test_reducer_keeps_both_hypotheses_unresolved_without_latency_increase() -> None:
    result = assess_mysql_pressure_evidence(
        _windows(
            **{
                "database.mysql.cpu.utilization_pct": (40.0, 90.0),
                "database.mysql.query.count": (100.0, 500.0),
                "dependency.latency": (20.0, 20.0),
            }
        )
    )

    assert result.mysql_saturation_status is CausalJoinStatus.UNRESOLVED
    assert result.request_growth_status is CausalJoinStatus.UNRESOLVED


def test_reducer_marks_every_hypothesis_unresolved_on_provider_gap() -> None:
    windows = _windows()
    windows["database.mysql.active_connections"] = _pair(
        "database.mysql.active_connections",
        20.0,
        20.0,
        complete=False,
    )

    result = assess_mysql_pressure_evidence(windows)

    assert result.mysql_saturation_status is CausalJoinStatus.UNRESOLVED
    assert result.request_growth_status is CausalJoinStatus.UNRESOLVED
    assert result.complete is False
    assert result.limitations == ("database.mysql.active_connections:provider_gap",)


def test_reducer_rejects_missing_reviewed_concept() -> None:
    windows = _windows()
    windows.pop(next(iter(MYSQL_PRESSURE_CONCEPTS)))

    with pytest.raises(ValueError, match="every reviewed concept"):
        assess_mysql_pressure_evidence(windows)


def _serialized(window: MetricWindow) -> dict[str, object]:
    return {
        "concept_id": window.concept_id,
        "resource_id": window.resource_id,
        "unit": window.unit,
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "samples": [
            {"timestamp": sample.timestamp.isoformat(), "value": sample.value}
            for sample in window.samples
        ],
        "complete": window.complete,
        "missing_reason": window.missing_reason,
        "evidence_refs": list(window.evidence_refs),
    }


def _function_arguments(
    windows: dict[str, tuple[MetricWindow, MetricWindow]],
) -> dict[str, object]:
    names = {
        "dependency.latency": "database_latency",
        "database.mysql.active_connections": "mysql_connections",
        "database.mysql.cpu.utilization_pct": "mysql_cpu",
        "database.mysql.query.count": "mysql_queries",
        "database.mysql.slow_query.count": "mysql_slow_queries",
    }
    return {
        f"{names[concept_id]}_{period}": _serialized(pair[index])
        for concept_id, pair in windows.items()
        for index, period in enumerate(("baseline", "current"))
    }


async def _invoke(arguments: dict[str, object]) -> dict[str, object]:
    declarations = (
        mysql_demand_bundle_function_type(),
        mysql_pressure_function_type(),
        mysql_saturation_bundle_function_type(),
    )
    release = build_ontology_release(function_types=declarations)
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declarations[0],
        mysql_demand_bundle_function(release),
    )
    registry.register_contextual(declarations[1], mysql_pressure_function(release))
    registry.register_contextual(
        declarations[2],
        mysql_saturation_bundle_function(release),
    )
    demand_arguments = {
        name: value
        for name, value in arguments.items()
        if name.startswith("database_latency") or name.startswith("mysql_queries")
    }
    saturation_arguments = {
        name: value for name, value in arguments.items() if name not in demand_arguments
    }
    context = FunctionInvocationContext(
        caller_agent="Bragi",
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
    )
    demand = await registry.invoke(
        MYSQL_DEMAND_BUNDLE_FUNCTION_NAME,
        demand_arguments,
        context=context,
    )
    saturation = await registry.invoke(
        MYSQL_SATURATION_BUNDLE_FUNCTION_NAME,
        saturation_arguments,
        context=context,
    )
    result = await registry.invoke(
        MYSQL_PRESSURE_FUNCTION_NAME,
        {"demand_evidence": demand, "saturation_evidence": saturation},
        context=context,
    )
    assert isinstance(result, dict)
    return result


def test_function_declares_every_metric_input_as_dependency_only() -> None:
    declarations = (
        mysql_demand_bundle_function_type(),
        mysql_pressure_function_type(),
        mysql_saturation_bundle_function_type(),
    )

    assert all(
        schema.get("x-fdai-dependency-only") is True
        for declaration in declarations
        for schema in declaration.input_schema["properties"].values()
    )
    assert tuple(len(item.input_schema["required"]) for item in declarations) == (4, 2, 6)
    assert all(item.required_role is CeilingRole.READER for item in declarations)
    assert all(item.network_allowed is False for item in declarations)
    assert all(item.credentials_allowed is False for item in declarations)


async def test_function_projects_complete_no_authority_evidence() -> None:
    result = await _invoke(
        _function_arguments(
            _windows(
                **{
                    "database.mysql.cpu.utilization_pct": (40.0, 90.0),
                    "database.mysql.slow_query.count": (1.0, 12.0),
                }
            )
        )
    )

    assert result["complete"] is True
    values = result["rows"][0]["values"]
    assert values["mysql_saturation_status"] == "supported"
    assert values["request_growth_status"] == "refuted"
    assert values["cause_claim_supported"] is False
    assert values["execution_authority"] is False


async def test_function_rejects_misaligned_metric_cutoffs() -> None:
    arguments = _function_arguments(_windows())
    current = arguments["mysql_cpu_current"]
    assert isinstance(current, dict)
    current["start"] = (NOW - timedelta(minutes=9)).isoformat()

    with pytest.raises(ValueError, match="cutoffs MUST align"):
        await _invoke(arguments)
