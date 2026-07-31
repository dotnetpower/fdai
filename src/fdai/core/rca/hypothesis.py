"""Immutable causal-hypothesis scoring and ontology projection."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

from fdai.shared.contracts.models import CausalEvidenceGrade
from fdai.shared.providers.ontology_instance import OntologyObjectRecord


class CausalHypothesisStatus(StrEnum):
    CANDIDATE = "candidate"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"
    CLOSED = "closed"


class CausalClosure(StrEnum):
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"
    UNSAFE = "unsafe"


@dataclass(frozen=True, slots=True)
class CausalEvidenceAssessment:
    temporal_precedence: float
    topological_reachability: float
    mechanism_fit: float
    intervention_consistency: float
    evidence_completeness: float
    ambiguity: int = 1
    supporting_refs: tuple[str, ...] = ()
    refuting_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (
            ("temporal_precedence", self.temporal_precedence),
            ("topological_reachability", self.topological_reachability),
            ("mechanism_fit", self.mechanism_fit),
            ("intervention_consistency", self.intervention_consistency),
            ("evidence_completeness", self.evidence_completeness),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} MUST be finite and in [0, 1]")
        if self.ambiguity < 1:
            raise ValueError("ambiguity MUST be >= 1")
        if any(not ref.strip() for ref in (*self.supporting_refs, *self.refuting_refs)):
            raise ValueError("evidence references MUST be non-empty")

    @property
    def confidence(self) -> float:
        weakest_factor = min(
            self.temporal_precedence,
            self.topological_reachability,
            self.mechanism_fit,
            self.intervention_consistency,
        )
        return round(
            weakest_factor * self.evidence_completeness / math.sqrt(self.ambiguity),
            6,
        )


@dataclass(frozen=True, slots=True)
class CausalHypothesisRecord:
    hypothesis_id: str
    incident_id: str
    status: CausalHypothesisStatus
    cause_ref: str
    effect_ref: str
    mechanism: str
    evidence_grade: CausalEvidenceGrade
    confidence: float
    ambiguity: int
    graph_revision: str
    evidence_cutoff: datetime
    method_version: str
    created_at: datetime
    supporting_refs: tuple[str, ...] = ()
    refuting_refs: tuple[str, ...] = ()
    closure: CausalClosure | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("hypothesis_id", self.hypothesis_id),
            ("incident_id", self.incident_id),
            ("cause_ref", self.cause_ref),
            ("effect_ref", self.effect_ref),
            ("mechanism", self.mechanism),
            ("graph_revision", self.graph_revision),
            ("method_version", self.method_version),
        ):
            if not value.strip():
                raise ValueError(f"{name} MUST be non-empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence MUST be in [0, 1]")
        if self.ambiguity < 1:
            raise ValueError("ambiguity MUST be >= 1")
        if self.evidence_cutoff.tzinfo is None or self.created_at.tzinfo is None:
            raise ValueError("causal hypothesis timestamps MUST be timezone-aware")
        if self.created_at < self.evidence_cutoff:
            raise ValueError("causal hypothesis creation MUST NOT precede evidence cutoff")

    def to_ontology_object(self) -> OntologyObjectRecord:
        return OntologyObjectRecord(
            id=self.hypothesis_id,
            object_type="CausalHypothesis",
            properties={
                "id": self.hypothesis_id,
                "incident_id": self.incident_id,
                "status": self.status.value,
                "cause_ref": self.cause_ref,
                "effect_ref": self.effect_ref,
                "mechanism": self.mechanism,
                "evidence_grade": self.evidence_grade.value,
                "confidence": self.confidence,
                "ambiguity": self.ambiguity,
                "graph_revision": self.graph_revision,
                "evidence_cutoff": self.evidence_cutoff,
                "method_version": self.method_version,
                "created_at": self.created_at,
                "closure": self.closure.value if self.closure is not None else None,
            },
        )


def build_causal_hypothesis(
    *,
    incident_id: str,
    cause_ref: str,
    effect_ref: str,
    mechanism: str,
    graph_revision: str,
    evidence_cutoff: datetime,
    method_version: str,
    evidence_grade: CausalEvidenceGrade,
    assessment: CausalEvidenceAssessment,
    created_at: datetime,
) -> CausalHypothesisRecord:
    identity = _identity(
        incident_id=incident_id,
        cause_ref=cause_ref,
        effect_ref=effect_ref,
        mechanism=mechanism,
        graph_revision=graph_revision,
        evidence_cutoff=evidence_cutoff,
        method_version=method_version,
    )
    if assessment.supporting_refs and assessment.refuting_refs:
        status = CausalHypothesisStatus.INCONCLUSIVE
    elif assessment.refuting_refs:
        status = CausalHypothesisStatus.REFUTED
    elif assessment.supporting_refs:
        status = CausalHypothesisStatus.SUPPORTED
    else:
        status = CausalHypothesisStatus.CANDIDATE
    return CausalHypothesisRecord(
        hypothesis_id=f"causal-{identity[:32]}",
        incident_id=incident_id,
        status=status,
        cause_ref=cause_ref,
        effect_ref=effect_ref,
        mechanism=mechanism,
        evidence_grade=evidence_grade,
        confidence=assessment.confidence,
        ambiguity=assessment.ambiguity,
        graph_revision=graph_revision,
        evidence_cutoff=evidence_cutoff,
        method_version=method_version,
        created_at=created_at,
        supporting_refs=assessment.supporting_refs,
        refuting_refs=assessment.refuting_refs,
    )


def close_causal_hypothesis(
    hypothesis: CausalHypothesisRecord,
    *,
    closure: CausalClosure,
    outcome_ref: str,
    created_at: datetime,
) -> CausalHypothesisRecord:
    if not outcome_ref.strip():
        raise ValueError("outcome_ref MUST be non-empty")
    if created_at.tzinfo is None or created_at < hypothesis.created_at:
        raise ValueError("closure time MUST be timezone-aware and monotonic")
    if closure is CausalClosure.REFUTED:
        status = CausalHypothesisStatus.REFUTED
        grade = CausalEvidenceGrade.ASSOCIATION
    elif closure is CausalClosure.INCONCLUSIVE:
        status = CausalHypothesisStatus.INCONCLUSIVE
        grade = hypothesis.evidence_grade
    elif closure is CausalClosure.UNSAFE:
        status = CausalHypothesisStatus.CLOSED
        grade = hypothesis.evidence_grade
    else:
        status = CausalHypothesisStatus.CLOSED
        grade = CausalEvidenceGrade.INTERVENTIONAL
    revision_id = _identity(
        prior=hypothesis.hypothesis_id,
        closure=closure.value,
        outcome_ref=outcome_ref,
    )
    return replace(
        hypothesis,
        hypothesis_id=f"causal-{revision_id[:32]}",
        status=status,
        evidence_grade=grade,
        created_at=created_at,
        closure=closure,
    )


def _identity(**values: object) -> str:
    encoded = json.dumps(values, default=_json_default, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    raise TypeError(f"unsupported identity value: {type(value).__name__}")


__all__ = [
    "build_causal_hypothesis",
    "CausalClosure",
    "CausalEvidenceAssessment",
    "CausalHypothesisRecord",
    "CausalHypothesisStatus",
    "close_causal_hypothesis",
]
