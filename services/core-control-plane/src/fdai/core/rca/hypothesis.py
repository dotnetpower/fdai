"""Immutable causal-hypothesis scoring and ontology projection."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.contracts.models import CausalEvidenceGrade
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    assess_decision_evidence_admission,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

CAUSAL_CLOSURE_EVIDENCE_PURPOSE = "causal-closure"


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


class CausalActionMode(StrEnum):
    """Highest mode a causal revision may support for its related action or experiment.

    `SHADOW` keeps the related action or chaos scenario evidence-only. `GATED` means the
    revision may enter the ordinary risk, approval, execution, and rollback gates as
    evidence; it never grants execution authority by itself.
    """

    SHADOW = "shadow"
    GATED = "gated"


_EVIDENCE_RANK: dict[CausalEvidenceGrade, int] = {
    CausalEvidenceGrade.ASSOCIATION: 0,
    CausalEvidenceGrade.PREDICTIVE_PRECEDENCE: 1,
    CausalEvidenceGrade.QUASI_EXPERIMENTAL: 2,
    CausalEvidenceGrade.INTERVENTIONAL: 3,
}


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
        supporting = tuple(sorted(set(self.supporting_refs)))
        refuting = tuple(sorted(set(self.refuting_refs)))
        object.__setattr__(self, "supporting_refs", supporting)
        object.__setattr__(self, "refuting_refs", refuting)

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
    if created_at.tzinfo is None or created_at < evidence_cutoff:
        raise ValueError("causal hypothesis creation MUST NOT precede evidence cutoff")
    identity = _identity(
        incident_id=incident_id,
        cause_ref=cause_ref,
        effect_ref=effect_ref,
        mechanism=mechanism,
        graph_revision=graph_revision,
        evidence_cutoff=evidence_cutoff,
        method_version=method_version,
        evidence_grade=evidence_grade.value,
        confidence=assessment.confidence,
        ambiguity=assessment.ambiguity,
        supporting_refs=assessment.supporting_refs,
        refuting_refs=assessment.refuting_refs,
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
    interventional_evidence_ref: str | None = None,
) -> CausalHypothesisRecord:
    if not outcome_ref.strip():
        raise ValueError("outcome_ref MUST be non-empty")
    if created_at.tzinfo is None or created_at < hypothesis.created_at:
        raise ValueError("closure time MUST be timezone-aware and monotonic")
    if closure is CausalClosure.CONFIRMED and (
        interventional_evidence_ref is None or not _is_sha256(interventional_evidence_ref)
    ):
        raise ValueError("confirmed closure requires interventional evidence SHA-256")
    if closure is CausalClosure.REFUTED:
        status = CausalHypothesisStatus.REFUTED
        grade = CausalEvidenceGrade.ASSOCIATION
    elif closure is CausalClosure.INCONCLUSIVE:
        status = CausalHypothesisStatus.INCONCLUSIVE
        grade = hypothesis.evidence_grade
    elif closure is CausalClosure.UNSAFE:
        status = CausalHypothesisStatus.CLOSED
        grade = CausalEvidenceGrade.ASSOCIATION
    else:
        status = CausalHypothesisStatus.CLOSED
        grade = CausalEvidenceGrade.INTERVENTIONAL
    if closure is not CausalClosure.CONFIRMED and (
        _EVIDENCE_RANK[grade] > _EVIDENCE_RANK[hypothesis.evidence_grade]
    ):
        grade = hypothesis.evidence_grade
    revision_id = _identity(
        prior=hypothesis.hypothesis_id,
        closure=closure.value,
        outcome_ref=outcome_ref,
        interventional_evidence_ref=interventional_evidence_ref,
    )
    return replace(
        hypothesis,
        hypothesis_id=f"causal-{revision_id[:32]}",
        status=status,
        evidence_grade=grade,
        created_at=created_at,
        closure=closure,
    )


def causal_action_mode(
    hypothesis: CausalHypothesisRecord,
    *,
    decision_evidence: DecisionEvidenceAdmission | None,
    evaluated_at: datetime,
) -> CausalActionMode:
    """Return the highest action mode this causal revision may support.

    Refuting evidence, an unsafe or refuted closure, an unresolved status, or an evidence
    grade below `quasi_experimental` keeps the related action or experiment in `shadow`.
    A `supported` status is trustworthy only because the runtime records supporting
    references after refutation completes; missing refutation stays `candidate`.

    `gated` additionally requires a current shared decision-critical evidence admission
    bound to this exact revision, scope, purpose, and graph revision. An absent, expired,
    or mismatched admission fails closed to `shadow`; it never raises the mode. The
    result is derived from the immutable revision and never grants execution authority.
    """

    if hypothesis.refuting_refs:
        return CausalActionMode.SHADOW
    if hypothesis.closure in {
        CausalClosure.REFUTED,
        CausalClosure.UNSAFE,
        CausalClosure.INCONCLUSIVE,
    }:
        return CausalActionMode.SHADOW
    if hypothesis.status not in {
        CausalHypothesisStatus.SUPPORTED,
        CausalHypothesisStatus.CLOSED,
    }:
        return CausalActionMode.SHADOW
    if (
        _EVIDENCE_RANK[hypothesis.evidence_grade]
        < _EVIDENCE_RANK[CausalEvidenceGrade.QUASI_EXPERIMENTAL]
    ):
        return CausalActionMode.SHADOW
    if causal_closure_rejection_reasons(
        hypothesis,
        decision_evidence=decision_evidence,
        evaluated_at=evaluated_at,
    ):
        return CausalActionMode.SHADOW
    return CausalActionMode.GATED


def causal_closure_rejection_reasons(
    hypothesis: CausalHypothesisRecord,
    *,
    decision_evidence: DecisionEvidenceAdmission | None,
    evaluated_at: datetime,
) -> tuple[str, ...]:
    """Return why the shared admission cannot admit this causal revision, if it cannot."""

    if decision_evidence is None:
        return ("decision_evidence_admission_missing",)
    return tuple(
        f"decision_evidence_{reason.value}"
        for reason in assess_decision_evidence_admission(
            decision_evidence,
            expected_evidence_digest=causal_closure_evidence_digest(hypothesis),
            expected_scope_digest=causal_closure_scope_digest(hypothesis),
            expected_purpose_id=CAUSAL_CLOSURE_EVIDENCE_PURPOSE,
            expected_source_revision=hypothesis.graph_revision,
            evaluated_at=evaluated_at,
        )
    )


def causal_closure_evidence_digest(hypothesis: CausalHypothesisRecord) -> str:
    """Return the exact closed causal revision digest without downstream mode fields."""

    return content_digest(
        {
            "ambiguity": hypothesis.ambiguity,
            "closure": hypothesis.closure.value if hypothesis.closure is not None else None,
            "confidence": hypothesis.confidence,
            "evidence_cutoff": hypothesis.evidence_cutoff.astimezone(UTC).isoformat(),
            "evidence_grade": hypothesis.evidence_grade.value,
            "graph_revision": hypothesis.graph_revision,
            "hypothesis_id": hypothesis.hypothesis_id,
            "incident_id": hypothesis.incident_id,
            "method_version": hypothesis.method_version,
            "refuting_refs": hypothesis.refuting_refs,
            "status": hypothesis.status.value,
            "supporting_refs": hypothesis.supporting_refs,
        }
    )


def causal_closure_scope_digest(hypothesis: CausalHypothesisRecord) -> str:
    """Return the exact incident, cause, effect, and mechanism scope of one revision."""

    return content_digest(
        {
            "cause_ref": hypothesis.cause_ref,
            "effect_ref": hypothesis.effect_ref,
            "incident_id": hypothesis.incident_id,
            "mechanism": hypothesis.mechanism,
        }
    )


def _identity(**values: object) -> str:
    encoded = json.dumps(values, default=_json_default, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    raise TypeError(f"unsupported identity value: {type(value).__name__}")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "CAUSAL_CLOSURE_EVIDENCE_PURPOSE",
    "build_causal_hypothesis",
    "causal_action_mode",
    "causal_closure_evidence_digest",
    "causal_closure_rejection_reasons",
    "causal_closure_scope_digest",
    "CausalActionMode",
    "CausalClosure",
    "CausalEvidenceAssessment",
    "CausalHypothesisRecord",
    "CausalHypothesisStatus",
    "close_causal_hypothesis",
]
