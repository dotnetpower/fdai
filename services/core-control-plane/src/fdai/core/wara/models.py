"""Immutable contracts for evidence-governed WARA assessment."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.rule_catalog.schema.wara_assessment import canonical_digest


class WaraApplicabilityStatus(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class WaraEvaluationStatus(StrEnum):
    EVALUATED = "evaluated"
    NOT_EVALUATED = "not_evaluated"
    BLOCKED = "blocked"


class WaraSatisfactionStatus(StrEnum):
    SATISFIED = "satisfied"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class WaraScopedResource:
    resource_id: str
    provider_resource_type: str
    workload_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.resource_id.strip() or not self.provider_resource_type.strip():
            raise ValueError("WARA scoped resource requires identity and provider type")
        if self.workload_tags != tuple(sorted(set(self.workload_tags))):
            raise ValueError("WARA scoped resource tags MUST be unique and ordered")


@dataclass(frozen=True, slots=True)
class WaraEvidenceReceipt:
    recommendation_id: str
    evidence_ref: str
    evidence_kind: str
    producer: str
    scope_digest: str
    source_revision: str
    inventory_generation: str
    observed_at: datetime
    recorded_at: datetime
    evidence_digest: str
    freshness_ceiling_seconds: int
    complete: bool
    truncated: bool
    conflicting: bool
    synthetic: bool
    provider_error: str | None
    outcome: WaraSatisfactionStatus
    applicability_approval_ref: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.evidence_ref.strip()
            or not self.evidence_kind.strip()
            or not self.producer.strip()
        ):
            raise ValueError("WARA evidence identity fields MUST be non-empty")
        if re.fullmatch(r"sha256:[a-f0-9]{64}", self.evidence_digest) is None:
            raise ValueError("WARA evidence digest MUST be lowercase SHA-256")
        if self.observed_at.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("WARA evidence timestamps MUST be timezone-aware")
        if self.recorded_at < self.observed_at:
            raise ValueError("WARA evidence recorded_at MUST follow observed_at")
        if self.freshness_ceiling_seconds < 1:
            raise ValueError("WARA evidence freshness ceiling MUST be positive")


@dataclass(frozen=True, slots=True)
class WaraAssessmentRequest:
    assessment_id: str
    framework_revision: str
    crosswalk_digest: str
    ontology_release: str
    inventory_generation: str
    workload_id: str
    resources: tuple[WaraScopedResource, ...]
    evaluated_at: datetime
    recorded_at: datetime
    evaluator_bindings_digest: str | None = None
    evidence: tuple[WaraEvidenceReceipt, ...] = ()

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.assessment_id,
                self.framework_revision,
                self.crosswalk_digest,
                self.ontology_release,
                self.inventory_generation,
                self.workload_id,
            )
        ):
            raise ValueError("WARA assessment request pins MUST be non-empty")
        if not self.resources:
            raise ValueError("WARA assessment requires at least one scoped resource")
        resource_ids = tuple(item.resource_id for item in self.resources)
        if resource_ids != tuple(sorted(set(resource_ids))):
            raise ValueError("WARA assessment resources MUST be unique and ordered")
        if self.evaluated_at.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("WARA assessment timestamps MUST be timezone-aware")
        if self.recorded_at < self.evaluated_at:
            raise ValueError("WARA assessment recorded_at MUST follow evaluated_at")
        if (
            self.evaluator_bindings_digest is not None
            and re.fullmatch(r"sha256:[a-f0-9]{64}", self.evaluator_bindings_digest) is None
        ):
            raise ValueError("WARA evaluator bindings digest MUST be lowercase SHA-256")

    @property
    def scope_digest(self) -> str:
        return canonical_digest(
            {
                "workload_id": self.workload_id,
                "resources": [
                    {
                        "resource_id": item.resource_id,
                        "provider_resource_type": item.provider_resource_type.casefold(),
                        "workload_tags": list(item.workload_tags),
                    }
                    for item in self.resources
                ],
            }
        )


@dataclass(frozen=True, slots=True)
class WaraControlResult:
    recommendation_id: str
    catalog_state: str
    mapping_state: str
    applicability: WaraApplicabilityStatus
    evaluation: WaraEvaluationStatus
    satisfaction: WaraSatisfactionStatus
    evidence_refs: tuple[str, ...]
    evidence_digests: tuple[str, ...]
    evidence_complete: bool
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "recommendation_id": self.recommendation_id,
            "catalog_state": self.catalog_state,
            "mapping_state": self.mapping_state,
            "applicability": self.applicability.value,
            "evaluation": self.evaluation.value,
            "satisfaction": self.satisfaction.value,
            "evidence_refs": list(self.evidence_refs),
            "evidence_digests": list(self.evidence_digests),
            "evidence_complete": self.evidence_complete,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class WaraAssessmentResult:
    assessment_id: str
    mode: str
    execution_authority: bool
    framework_revision: str
    crosswalk_digest: str
    evaluator_bindings_digest: str | None
    ontology_release: str
    inventory_generation: str
    workload_id: str
    scope_digest: str
    evaluated_at: datetime
    recorded_at: datetime
    controls: tuple[WaraControlResult, ...]
    aggregate_counts: dict[str, int]
    result_digest: str

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "assessment_id": self.assessment_id,
            "mode": self.mode,
            "execution_authority": self.execution_authority,
            "framework_revision": self.framework_revision,
            "crosswalk_digest": self.crosswalk_digest,
            "ontology_release": self.ontology_release,
            "inventory_generation": self.inventory_generation,
            "workload_id": self.workload_id,
            "scope_digest": self.scope_digest,
            "evaluated_at": self.evaluated_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
            "controls": [item.to_dict() for item in self.controls],
            "aggregate_counts": dict(sorted(self.aggregate_counts.items())),
        }
        if self.evaluator_bindings_digest is not None:
            value["evaluator_bindings_digest"] = self.evaluator_bindings_digest
        if include_digest:
            value["result_digest"] = self.result_digest
        return value


__all__ = [
    "WaraApplicabilityStatus",
    "WaraAssessmentRequest",
    "WaraAssessmentResult",
    "WaraControlResult",
    "WaraEvaluationStatus",
    "WaraEvidenceReceipt",
    "WaraSatisfactionStatus",
    "WaraScopedResource",
]
