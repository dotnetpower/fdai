"""Immutable contracts for evidence-governed MSRC CSAF vulnerability assessment."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.rule_catalog.schema.msrc_csaf import CsafDisposition, CsafThreatExploitStatus
from fdai.rule_catalog.schema.wara_assessment import canonical_digest
from fdai.shared.contracts.models import Severity

_SHA256_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_CVE_RE = re.compile(r"^(?:CVE-[0-9]{4}-[0-9]{4,7}|ADV[0-9]{6})$")
_PROP_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
ScalarProperty = str | bool | int


class CsafExposureStatus(StrEnum):
    AFFECTED = "affected"
    MITIGATED = "mitigated"
    FIXED = "fixed"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class CsafEvaluationStatus(StrEnum):
    EVALUATED = "evaluated"
    NOT_EVALUATED = "not_evaluated"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class CsafScopedResource:
    resource_id: str
    provider_resource_type: str
    observed_at: datetime
    properties: Mapping[str, ScalarProperty]
    workload_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.resource_id.strip() or not self.provider_resource_type.strip():
            raise ValueError("CSAF scoped resource requires non-empty identity and provider type")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("CSAF scoped resource observed_at MUST be timezone-aware")
        if self.workload_tags != tuple(sorted(set(self.workload_tags))):
            raise ValueError("CSAF scoped resource workload_tags MUST be unique and ordered")
        normalized_props: dict[str, ScalarProperty] = {}
        for key in sorted(self.properties):
            if not isinstance(key, str) or _PROP_KEY_RE.fullmatch(key) is None:
                raise ValueError(f"CSAF scoped resource property key {key!r} is invalid")
            val = self.properties[key]
            if not isinstance(val, (str, bool, int)):
                raise ValueError(f"CSAF scoped resource property {key!r} MUST be str, bool, or int")
            normalized_props[key] = val
        object.__setattr__(self, "properties", normalized_props)


@dataclass(frozen=True, slots=True)
class CsafEvidenceReceipt:
    cve_id: str
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
    outcome: CsafExposureStatus

    def __post_init__(self) -> None:
        if _CVE_RE.fullmatch(self.cve_id) is None:
            raise ValueError("CSAF evidence receipt cve_id MUST be a canonical CVE identifier")
        if (
            not self.evidence_ref.strip()
            or not self.evidence_kind.strip()
            or not self.producer.strip()
        ):
            raise ValueError("CSAF evidence receipt identity fields MUST be non-empty")
        if _SHA256_RE.fullmatch(self.evidence_digest) is None:
            raise ValueError("CSAF evidence digest MUST be lowercase SHA-256")
        if _SHA256_RE.fullmatch(self.scope_digest) is None:
            raise ValueError("CSAF evidence scope_digest MUST be lowercase SHA-256")
        if (
            self.observed_at.tzinfo is None
            or self.observed_at.utcoffset() is None
            or self.recorded_at.tzinfo is None
            or self.recorded_at.utcoffset() is None
        ):
            raise ValueError("CSAF evidence timestamps MUST be timezone-aware")
        if self.recorded_at < self.observed_at:
            raise ValueError("CSAF evidence recorded_at MUST follow observed_at")
        if self.freshness_ceiling_seconds < 1:
            raise ValueError("CSAF evidence freshness ceiling MUST be positive")


@dataclass(frozen=True, slots=True)
class CsafAssessmentRequest:
    assessment_id: str
    source_revision: str
    crosswalk_digest: str
    advisories_digest: str
    ontology_release: str
    inventory_generation: str
    workload_id: str
    resources: tuple[CsafScopedResource, ...]
    evaluated_at: datetime
    recorded_at: datetime
    evidence: tuple[CsafEvidenceReceipt, ...] = ()

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.assessment_id,
                self.source_revision,
                self.crosswalk_digest,
                self.advisories_digest,
                self.ontology_release,
                self.inventory_generation,
                self.workload_id,
            )
        ):
            raise ValueError("CSAF assessment request pins MUST be non-empty")
        for label, digest in (
            ("crosswalk", self.crosswalk_digest),
            ("advisories", self.advisories_digest),
        ):
            if _SHA256_RE.fullmatch(digest) is None:
                raise ValueError(f"CSAF {label} digest MUST be lowercase SHA-256")
        if not self.resources:
            raise ValueError("CSAF assessment requires at least one scoped resource")
        resource_ids = tuple(item.resource_id for item in self.resources)
        if resource_ids != tuple(sorted(set(resource_ids))):
            raise ValueError("CSAF assessment resources MUST be unique and ordered by resource_id")
        if (
            self.evaluated_at.tzinfo is None
            or self.evaluated_at.utcoffset() is None
            or self.recorded_at.tzinfo is None
            or self.recorded_at.utcoffset() is None
        ):
            raise ValueError("CSAF assessment timestamps MUST be timezone-aware")
        if self.recorded_at < self.evaluated_at:
            raise ValueError("CSAF assessment recorded_at MUST follow evaluated_at")

    @property
    def scope_digest(self) -> str:
        return canonical_digest(
            {
                "workload_id": self.workload_id,
                "resources": [
                    {
                        "resource_id": item.resource_id,
                        "provider_resource_type": item.provider_resource_type.casefold(),
                        "observed_at": item.observed_at.isoformat(),
                        "properties": dict(sorted(item.properties.items())),
                        "workload_tags": list(item.workload_tags),
                    }
                    for item in self.resources
                ],
            }
        )


@dataclass(frozen=True, slots=True)
class CsafVulnerabilityFinding:
    cve_id: str
    advisory_tracking_id: str
    title: str
    severity: Severity
    cvss_base_score: float
    exploit_status: CsafThreatExploitStatus
    disposition: CsafDisposition
    mapping_state: str
    evaluation: CsafEvaluationStatus
    exposure: CsafExposureStatus
    affected_resource_ids: tuple[str, ...]
    mitigated_resource_ids: tuple[str, ...]
    fixed_resource_ids: tuple[str, ...]
    unknown_resource_ids: tuple[str, ...]
    recommended_action_type: str | None
    evidence_refs: tuple[str, ...]
    evidence_digests: tuple[str, ...]
    evidence_complete: bool
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not math.isfinite(self.cvss_base_score) or not 0.0 <= self.cvss_base_score <= 10.0:
            raise ValueError("CsafVulnerabilityFinding.cvss_base_score MUST be in [0.0, 10.0]")

    def to_dict(self) -> dict[str, object]:
        return {
            "cve_id": self.cve_id,
            "advisory_tracking_id": self.advisory_tracking_id,
            "title": self.title,
            "severity": self.severity.value,
            "cvss_base_score": self.cvss_base_score,
            "exploit_status": self.exploit_status.value,
            "disposition": self.disposition.value,
            "mapping_state": self.mapping_state,
            "evaluation": self.evaluation.value,
            "exposure": self.exposure.value,
            "affected_resource_ids": list(self.affected_resource_ids),
            "mitigated_resource_ids": list(self.mitigated_resource_ids),
            "fixed_resource_ids": list(self.fixed_resource_ids),
            "unknown_resource_ids": list(self.unknown_resource_ids),
            "recommended_action_type": self.recommended_action_type,
            "evidence_refs": list(self.evidence_refs),
            "evidence_digests": list(self.evidence_digests),
            "evidence_complete": self.evidence_complete,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class CsafAssessmentResult:
    assessment_id: str
    mode: str
    execution_authority: bool
    source_revision: str
    crosswalk_digest: str
    advisories_digest: str
    ontology_release: str
    inventory_generation: str
    workload_id: str
    scope_digest: str
    evaluated_at: datetime
    recorded_at: datetime
    findings: tuple[CsafVulnerabilityFinding, ...]
    aggregate_counts: dict[str, int]
    result_digest: str

    def __post_init__(self) -> None:
        if self.mode != "shadow" or self.execution_authority is not False:
            raise ValueError("CSAF assessment results are shadow-only and never grant authority")
        if _SHA256_RE.fullmatch(self.result_digest) is None:
            raise ValueError("CSAF assessment result_digest MUST be lowercase SHA-256")

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "assessment_id": self.assessment_id,
            "mode": self.mode,
            "execution_authority": self.execution_authority,
            "source_revision": self.source_revision,
            "crosswalk_digest": self.crosswalk_digest,
            "advisories_digest": self.advisories_digest,
            "ontology_release": self.ontology_release,
            "inventory_generation": self.inventory_generation,
            "workload_id": self.workload_id,
            "scope_digest": self.scope_digest,
            "evaluated_at": self.evaluated_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
            "findings": [item.to_dict() for item in self.findings],
            "aggregate_counts": dict(sorted(self.aggregate_counts.items())),
        }
        if include_digest:
            payload["result_digest"] = self.result_digest
        return payload


__all__ = [
    "CsafAssessmentRequest",
    "CsafAssessmentResult",
    "CsafEvaluationStatus",
    "CsafEvidenceReceipt",
    "CsafExposureStatus",
    "CsafScopedResource",
    "CsafVulnerabilityFinding",
    "ScalarProperty",
]
