"""Pure MySQL pressure evidence reduction for bounded SRE investigations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from fdai.core.detection.series import MetricSample
from fdai.core.ontology_platform.functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
)
from fdai.core.ontology_platform.metric_semantics import (
    CausalJoinStatus,
    MetricAggregation,
    MetricWindow,
    MetricWindowComparison,
    compare_aligned_windows,
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

MYSQL_PRESSURE_CONCEPTS = MappingProxyType(
    {
        "database.mysql.active_connections": MetricAggregation.MAXIMUM,
        "database.mysql.cpu.utilization_pct": MetricAggregation.AVERAGE,
        "database.mysql.query.count": MetricAggregation.SUM,
        "database.mysql.slow_query.count": MetricAggregation.SUM,
        "dependency.latency": MetricAggregation.AVERAGE,
    }
)
MYSQL_PRESSURE_FUNCTION_NAME = "query.mysql_pressure_evidence"
MYSQL_DEMAND_BUNDLE_FUNCTION_NAME = "query.mysql_demand_metric_bundle"
MYSQL_SATURATION_BUNDLE_FUNCTION_NAME = "query.mysql_saturation_metric_bundle"
_INPUTS = MappingProxyType(
    {
        "database_latency_baseline": "dependency.latency",
        "database_latency_current": "dependency.latency",
        "mysql_connections_baseline": "database.mysql.active_connections",
        "mysql_connections_current": "database.mysql.active_connections",
        "mysql_cpu_baseline": "database.mysql.cpu.utilization_pct",
        "mysql_cpu_current": "database.mysql.cpu.utilization_pct",
        "mysql_queries_baseline": "database.mysql.query.count",
        "mysql_queries_current": "database.mysql.query.count",
        "mysql_slow_queries_baseline": "database.mysql.slow_query.count",
        "mysql_slow_queries_current": "database.mysql.slow_query.count",
    }
)
_DEMAND_INPUTS = MappingProxyType(
    {
        name: concept
        for name, concept in _INPUTS.items()
        if name.startswith("database_latency") or name.startswith("mysql_queries")
    }
)
_SATURATION_INPUTS = MappingProxyType(
    {name: concept for name, concept in _INPUTS.items() if name not in _DEMAND_INPUTS}
)


@dataclass(frozen=True, slots=True)
class MysqlPressureEvidenceResult:
    """Bounded competing-hypothesis evidence without a root-cause or action grant."""

    comparisons: Mapping[str, MetricWindowComparison]
    mysql_saturation_status: CausalJoinStatus
    request_growth_status: CausalJoinStatus
    complete: bool
    limitations: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    cause_claim_supported: bool = False
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if set(self.comparisons) != set(MYSQL_PRESSURE_CONCEPTS):
            raise ValueError("MySQL pressure comparisons MUST cover every reviewed concept")
        if self.complete != (not self.limitations):
            raise ValueError("MySQL pressure completeness and limitations are inconsistent")
        if not self.evidence_refs:
            raise ValueError("MySQL pressure evidence MUST cite at least one source")
        if self.cause_claim_supported or self.execution_authority:
            raise ValueError("MySQL pressure evidence cannot grant cause or execution authority")
        object.__setattr__(self, "comparisons", MappingProxyType(dict(self.comparisons)))


def assess_mysql_pressure_evidence(
    windows: Mapping[str, tuple[MetricWindow, MetricWindow]],
) -> MysqlPressureEvidenceResult:
    """Compare equal windows and disposition two hypotheses without inferring causation."""

    if set(windows) != set(MYSQL_PRESSURE_CONCEPTS):
        raise ValueError("MySQL pressure windows MUST cover every reviewed concept")
    comparisons = {
        concept_id: compare_aligned_windows(
            windows[concept_id][0],
            windows[concept_id][1],
            aggregation=aggregation,
        )
        for concept_id, aggregation in MYSQL_PRESSURE_CONCEPTS.items()
    }
    limitations = tuple(
        sorted(
            f"{concept_id}:{comparison.reason or 'incomplete'}"
            for concept_id, comparison in comparisons.items()
            if not comparison.complete
        )
    )
    evidence_refs = tuple(
        dict.fromkeys(
            ref for comparison in comparisons.values() for ref in comparison.evidence_refs
        )
    )
    if limitations:
        saturation = CausalJoinStatus.UNRESOLVED
        request_growth = CausalJoinStatus.UNRESOLVED
    else:
        latency_increased = _increased(comparisons["dependency.latency"])
        saturation_signals = (
            _increased(comparisons["database.mysql.cpu.utilization_pct"]),
            _increased(comparisons["database.mysql.active_connections"]),
            _increased(comparisons["database.mysql.slow_query.count"]),
        )
        query_volume_increased = _increased(comparisons["database.mysql.query.count"])
        saturation = _disposition(
            symptom_increased=latency_increased,
            supporting_signals=saturation_signals,
        )
        request_growth = _disposition(
            symptom_increased=latency_increased,
            supporting_signals=(query_volume_increased,),
        )
    return MysqlPressureEvidenceResult(
        comparisons=comparisons,
        mysql_saturation_status=saturation,
        request_growth_status=request_growth,
        complete=not limitations,
        limitations=limitations,
        evidence_refs=evidence_refs,
    )


def mysql_pressure_function_type() -> OntologyFunctionType:
    """Declare the dependency-only MySQL pressure evidence reducer."""

    return _function_type(
        name=MYSQL_PRESSURE_FUNCTION_NAME,
        required={
            "demand_evidence": {"type": "object", "x-fdai-dependency-only": True},
            "saturation_evidence": {"type": "object", "x-fdai-dependency-only": True},
        },
    )


def mysql_demand_bundle_function_type() -> OntologyFunctionType:
    """Declare the four-input demand and latency metric bundle."""

    return _function_type(
        name=MYSQL_DEMAND_BUNDLE_FUNCTION_NAME,
        required={
            name: {"type": "object", "x-fdai-dependency-only": True} for name in _DEMAND_INPUTS
        },
    )


def mysql_saturation_bundle_function_type() -> OntologyFunctionType:
    """Declare the six-input MySQL saturation metric bundle."""

    return _function_type(
        name=MYSQL_SATURATION_BUNDLE_FUNCTION_NAME,
        required={
            name: {"type": "object", "x-fdai-dependency-only": True} for name in _SATURATION_INPUTS
        },
    )


def _function_type(
    *,
    name: str,
    required: Mapping[str, Mapping[str, object]],
) -> OntologyFunctionType:
    return OntologyFunctionType(
        name=name,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": list(required),
            "properties": dict(required),
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
        max_output_bytes=65_536,
        network_allowed=False,
        credentials_allowed=False,
    )


def mysql_pressure_function(ontology_release: OntologyRelease) -> ContextualOntologyFunction:
    """Reduce issued metric dependencies without making a root-cause claim."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        MYSQL_PRESSURE_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("MySQL pressure purpose does not match invocation context")
        demand = _bundle_windows(arguments["demand_evidence"], expected_inputs=_DEMAND_INPUTS)
        saturation = _bundle_windows(
            arguments["saturation_evidence"],
            expected_inputs=_SATURATION_INPUTS,
        )
        raw_windows = {**demand, **saturation}
        parsed = {
            name: _metric_window(raw_windows[name], expected_concept=concept_id)
            for name, concept_id in _INPUTS.items()
        }
        _verify_common_cutoffs(parsed)
        windows = {
            concept_id: (
                parsed[_input_name(concept_id, "baseline")],
                parsed[_input_name(concept_id, "current")],
            )
            for concept_id in MYSQL_PRESSURE_CONCEPTS
        }
        result = assess_mysql_pressure_evidence(windows)
        values: dict[str, object] = {
            "mysql_saturation_status": result.mysql_saturation_status.value,
            "request_growth_status": result.request_growth_status.value,
            "cause_claim_supported": False,
            "execution_authority": False,
            "limitations": list(result.limitations),
            "evidence_refs": list(result.evidence_refs),
        }
        for concept_id, comparison in result.comparisons.items():
            prefix = concept_id.replace(".", "_")
            values[f"{prefix}_baseline"] = comparison.baseline_value
            values[f"{prefix}_current"] = comparison.current_value
            values[f"{prefix}_change"] = comparison.absolute_change
        table = QueryTable(
            rows=(QueryRow.from_values("mysql-pressure-evidence", values),),
            complete=result.complete,
            truncation_reason=None if result.complete else "mysql_pressure_evidence_incomplete",
        )
        return cast(dict[str, object], json.loads(table.canonical_json()))

    return evaluate


def mysql_demand_bundle_function(ontology_release: OntologyRelease) -> ContextualOntologyFunction:
    """Validate and bundle demand and database-latency metric windows."""

    return _metric_bundle_function(
        ontology_release,
        function_name=MYSQL_DEMAND_BUNDLE_FUNCTION_NAME,
        inputs=_DEMAND_INPUTS,
        row_id="mysql-demand-metric-bundle",
    )


def mysql_saturation_bundle_function(
    ontology_release: OntologyRelease,
) -> ContextualOntologyFunction:
    """Validate and bundle MySQL saturation metric windows."""

    return _metric_bundle_function(
        ontology_release,
        function_name=MYSQL_SATURATION_BUNDLE_FUNCTION_NAME,
        inputs=_SATURATION_INPUTS,
        row_id="mysql-saturation-metric-bundle",
    )


def _metric_bundle_function(
    ontology_release: OntologyRelease,
    *,
    function_name: str,
    inputs: Mapping[str, str],
    row_id: str,
) -> ContextualOntologyFunction:
    ontology_release.type_ref(OntologyDeclarationKind.FUNCTION, function_name)

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("MySQL metric bundle purpose does not match invocation context")
        parsed = {
            name: _metric_window(arguments[name], expected_concept=concept_id)
            for name, concept_id in inputs.items()
        }
        _verify_common_cutoffs(parsed)
        complete = all(window.complete for window in parsed.values())
        table = QueryTable(
            rows=(QueryRow.from_values(row_id, {"windows": dict(arguments)}),),
            complete=complete,
            truncation_reason=None if complete else "mysql_metric_bundle_incomplete",
        )
        return cast(dict[str, object], json.loads(table.canonical_json()))

    return evaluate


def _increased(comparison: MetricWindowComparison) -> bool:
    return comparison.absolute_change is not None and comparison.absolute_change > 0


def _disposition(
    *,
    symptom_increased: bool,
    supporting_signals: tuple[bool, ...],
) -> CausalJoinStatus:
    if not symptom_increased:
        return CausalJoinStatus.UNRESOLVED
    if any(supporting_signals):
        return CausalJoinStatus.SUPPORTED
    return CausalJoinStatus.REFUTED


def _input_name(concept_id: str, window: str) -> str:
    selected = tuple(
        name
        for name, candidate in _INPUTS.items()
        if candidate == concept_id and name.endswith(f"_{window}")
    )
    if len(selected) != 1:
        raise ValueError("MySQL pressure input mapping is invalid")
    return selected[0]


def _bundle_windows(
    value: object,
    *,
    expected_inputs: Mapping[str, str],
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("MySQL metric bundle MUST be a query table")
    rows = value.get("rows")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise ValueError("MySQL metric bundle MUST contain one row")
    values = rows[0].get("values")
    windows = values.get("windows") if isinstance(values, Mapping) else None
    if not isinstance(windows, Mapping) or set(windows) != set(expected_inputs):
        raise ValueError("MySQL metric bundle window set is invalid")
    return dict(windows)


def _metric_window(value: object, *, expected_concept: str) -> MetricWindow:
    if not isinstance(value, Mapping) or value.get("concept_id") != expected_concept:
        raise ValueError("MySQL pressure metric concept is invalid")
    samples_raw = value.get("samples")
    evidence_raw = value.get("evidence_refs")
    if not isinstance(samples_raw, list) or not isinstance(evidence_raw, list):
        raise ValueError("MySQL pressure metric evidence is invalid")
    samples: list[MetricSample] = []
    for sample in samples_raw:
        if not isinstance(sample, Mapping):
            raise ValueError("MySQL pressure metric sample is invalid")
        timestamp = sample.get("timestamp")
        number = sample.get("value")
        if (
            not isinstance(timestamp, str)
            or isinstance(number, bool)
            or not isinstance(number, (int, float))
        ):
            raise ValueError("MySQL pressure metric sample is invalid")
        samples.append(
            MetricSample(
                timestamp=datetime.fromisoformat(timestamp),
                value=float(number),
            )
        )
    required_text = ("resource_id", "unit", "start", "end")
    if any(not isinstance(value.get(key), str) for key in required_text) or not isinstance(
        value.get("complete"), bool
    ):
        raise ValueError("MySQL pressure metric window is invalid")
    return MetricWindow(
        concept_id=expected_concept,
        resource_id=str(value["resource_id"]),
        unit=str(value["unit"]),
        start=datetime.fromisoformat(str(value["start"])),
        end=datetime.fromisoformat(str(value["end"])),
        samples=tuple(samples),
        complete=bool(value["complete"]),
        missing_reason=(
            str(value["missing_reason"]) if value.get("missing_reason") is not None else None
        ),
        evidence_refs=tuple(str(item) for item in evidence_raw),
    )


def _verify_common_cutoffs(windows: Mapping[str, MetricWindow]) -> None:
    baseline_bounds = {
        (window.start, window.end) for name, window in windows.items() if name.endswith("_baseline")
    }
    current_bounds = {
        (window.start, window.end) for name, window in windows.items() if name.endswith("_current")
    }
    if len(baseline_bounds) != 1 or len(current_bounds) != 1:
        raise ValueError("MySQL pressure metric cutoffs MUST align")


__all__ = [
    "MYSQL_PRESSURE_CONCEPTS",
    "MYSQL_DEMAND_BUNDLE_FUNCTION_NAME",
    "MYSQL_PRESSURE_FUNCTION_NAME",
    "MYSQL_SATURATION_BUNDLE_FUNCTION_NAME",
    "MysqlPressureEvidenceResult",
    "assess_mysql_pressure_evidence",
    "mysql_demand_bundle_function",
    "mysql_demand_bundle_function_type",
    "mysql_pressure_function",
    "mysql_pressure_function_type",
    "mysql_saturation_bundle_function",
    "mysql_saturation_bundle_function_type",
]
