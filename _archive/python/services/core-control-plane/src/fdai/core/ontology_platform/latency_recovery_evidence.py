"""Pure service and dependency latency recovery evidence reduction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from fdai.core.ontology_platform.functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
)
from fdai.core.ontology_platform.metric_semantics import MetricWindowComparison
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

LATENCY_RECOVERY_FUNCTION_NAME = "query.latency_recovery_evidence"
_SERVICE_LATENCY = "service.latency"
_DEPENDENCY_LATENCY = "dependency.latency"


class LatencyRecoveryStatus(StrEnum):
    """Evidence-bounded disposition for both required recovery measures."""

    RECOVERED = "recovered"
    NOT_RECOVERED = "not_recovered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, slots=True)
class LatencyRecoveryEvidenceResult:
    """Two-measure recovery result with no cause or execution authority."""

    status: LatencyRecoveryStatus
    service_latency: MetricWindowComparison
    dependency_latency: MetricWindowComparison
    complete: bool
    limitations: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    recovery_verified: bool
    cause_claim_supported: bool = False
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.complete != (not self.limitations):
            raise ValueError("latency recovery completeness and limitations are inconsistent")
        if self.recovery_verified != (self.status is LatencyRecoveryStatus.RECOVERED):
            raise ValueError("latency recovery verification and status are inconsistent")
        if not self.evidence_refs:
            raise ValueError("latency recovery evidence MUST cite at least one source")
        if self.cause_claim_supported or self.execution_authority:
            raise ValueError("latency recovery cannot grant cause or execution authority")


def assess_latency_recovery(
    *,
    service_latency: MetricWindowComparison,
    dependency_latency: MetricWindowComparison,
) -> LatencyRecoveryEvidenceResult:
    """Require both current averages to return to or below their original baselines."""

    expected = {
        service_latency.concept_id: _SERVICE_LATENCY,
        dependency_latency.concept_id: _DEPENDENCY_LATENCY,
    }
    if expected != {_SERVICE_LATENCY: _SERVICE_LATENCY, _DEPENDENCY_LATENCY: _DEPENDENCY_LATENCY}:
        raise ValueError("latency recovery comparisons use unexpected metric concepts")
    if (
        service_latency.baseline_start != dependency_latency.baseline_start
        or service_latency.baseline_end != dependency_latency.baseline_end
        or service_latency.current_start != dependency_latency.current_start
        or service_latency.current_end != dependency_latency.current_end
    ):
        raise ValueError("latency recovery comparison cutoffs MUST align")
    limitations = tuple(
        sorted(
            f"{item.concept_id}:{item.reason or 'incomplete'}"
            for item in (service_latency, dependency_latency)
            if not item.complete
        )
    )
    evidence_refs = tuple(
        dict.fromkeys((*service_latency.evidence_refs, *dependency_latency.evidence_refs))
    )
    if limitations:
        status = LatencyRecoveryStatus.INSUFFICIENT_EVIDENCE
    elif _at_or_below_baseline(service_latency) and _at_or_below_baseline(dependency_latency):
        status = LatencyRecoveryStatus.RECOVERED
    else:
        status = LatencyRecoveryStatus.NOT_RECOVERED
    return LatencyRecoveryEvidenceResult(
        status=status,
        service_latency=service_latency,
        dependency_latency=dependency_latency,
        complete=not limitations,
        limitations=limitations,
        evidence_refs=evidence_refs,
        recovery_verified=status is LatencyRecoveryStatus.RECOVERED,
    )


def latency_recovery_function_type() -> OntologyFunctionType:
    """Declare the dependency-only latency recovery reducer."""

    dependencies = {
        "service_latency": {"type": "object", "x-fdai-dependency-only": True},
        "dependency_latency": {"type": "object", "x-fdai-dependency-only": True},
    }
    return OntologyFunctionType(
        name=LATENCY_RECOVERY_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": list(dependencies),
            "properties": dependencies,
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
        read_sets=["BusinessService", "Resource"],
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


def latency_recovery_function(ontology_release: OntologyRelease) -> ContextualOntologyFunction:
    """Reduce two issued metric comparisons without inferring a cause."""

    ontology_release.type_ref(OntologyDeclarationKind.FUNCTION, LATENCY_RECOVERY_FUNCTION_NAME)

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("latency recovery purpose does not match invocation context")
        service_latency = _comparison(arguments["service_latency"], _SERVICE_LATENCY)
        dependency_latency = _comparison(arguments["dependency_latency"], _DEPENDENCY_LATENCY)
        result = assess_latency_recovery(
            service_latency=service_latency,
            dependency_latency=dependency_latency,
        )
        values = {
            "status": result.status.value,
            "service_latency_baseline": service_latency.baseline_value,
            "service_latency_current": service_latency.current_value,
            "dependency_latency_baseline": dependency_latency.baseline_value,
            "dependency_latency_current": dependency_latency.current_value,
            "recovery_verified": result.recovery_verified,
            "cause_claim_supported": False,
            "execution_authority": False,
            "limitations": list(result.limitations),
            "evidence_refs": list(result.evidence_refs),
        }
        table = QueryTable(
            rows=(QueryRow.from_values("latency-recovery-evidence", values),),
            complete=result.complete,
            truncation_reason=None if result.complete else "latency_recovery_evidence_incomplete",
        )
        return cast(dict[str, object], json.loads(table.canonical_json()))

    return evaluate


def _at_or_below_baseline(comparison: MetricWindowComparison) -> bool:
    return (
        comparison.baseline_value is not None
        and comparison.current_value is not None
        and comparison.current_value <= comparison.baseline_value
    )


def _comparison(value: object, expected_concept: str) -> MetricWindowComparison:
    if not isinstance(value, Mapping) or value.get("concept_id") != expected_concept:
        raise ValueError("latency recovery comparison concept is invalid")
    required_text = (
        "resource_id",
        "unit",
        "baseline_start",
        "baseline_end",
        "current_start",
        "current_end",
    )
    if any(not isinstance(value.get(field), str) for field in required_text):
        raise ValueError("latency recovery comparison fields are invalid")
    evidence_refs = value.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not isinstance(value.get("complete"), bool):
        raise ValueError("latency recovery comparison evidence is invalid")
    return MetricWindowComparison(
        concept_id=expected_concept,
        resource_id=str(value["resource_id"]),
        unit=str(value["unit"]),
        baseline_start=datetime.fromisoformat(str(value["baseline_start"])),
        baseline_end=datetime.fromisoformat(str(value["baseline_end"])),
        current_start=datetime.fromisoformat(str(value["current_start"])),
        current_end=datetime.fromisoformat(str(value["current_end"])),
        baseline_value=_optional_number(value.get("baseline_value")),
        current_value=_optional_number(value.get("current_value")),
        absolute_change=_optional_number(value.get("absolute_change")),
        relative_change=_optional_number(value.get("relative_change")),
        complete=bool(value["complete"]),
        reason=str(value["reason"]) if value.get("reason") is not None else None,
        evidence_refs=tuple(str(item) for item in evidence_refs),
    )


def _optional_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("latency recovery comparison number is invalid")
    return float(value)


__all__ = [
    "LATENCY_RECOVERY_FUNCTION_NAME",
    "LatencyRecoveryEvidenceResult",
    "LatencyRecoveryStatus",
    "assess_latency_recovery",
    "latency_recovery_function",
    "latency_recovery_function_type",
]
