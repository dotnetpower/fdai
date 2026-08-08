from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.rca.hypothesis import (
    CausalClosure,
    CausalEvidenceAssessment,
    CausalHypothesisStatus,
    build_causal_hypothesis,
    close_causal_hypothesis,
)
from fdai.shared.contracts.models import CausalEvidenceGrade

_NOW = datetime(2026, 7, 31, tzinfo=UTC)


def _assessment(**overrides: object) -> CausalEvidenceAssessment:
    values: dict[str, object] = {
        "temporal_precedence": 0.9,
        "topological_reachability": 0.8,
        "mechanism_fit": 0.7,
        "intervention_consistency": 0.6,
        "evidence_completeness": 0.5,
        "ambiguity": 1,
        "supporting_refs": ("event:change",),
    }
    values.update(overrides)
    return CausalEvidenceAssessment(**values)  # type: ignore[arg-type]


def _hypothesis(**assessment: object):  # type: ignore[no-untyped-def]
    return build_causal_hypothesis(
        incident_id="incident-1",
        cause_ref="change-1",
        effect_ref="finding-1",
        mechanism="deployment_error",
        graph_revision="graph-1",
        evidence_cutoff=_NOW,
        method_version="causal-v1",
        evidence_grade=CausalEvidenceGrade.PREDICTIVE_PRECEDENCE,
        assessment=_assessment(**assessment),
        created_at=_NOW,
    )


def test_confidence_uses_weakest_factor_completeness_and_ambiguity() -> None:
    assert _hypothesis().confidence == 0.3
    assert _hypothesis(ambiguity=4).confidence == 0.15


def test_refuting_only_evidence_marks_candidate_refuted() -> None:
    hypothesis = _hypothesis(supporting_refs=(), refuting_refs=("metric:healthy",))
    assert hypothesis.status is CausalHypothesisStatus.REFUTED


def test_competing_support_and_refutation_is_inconclusive() -> None:
    hypothesis = _hypothesis(refuting_refs=("metric:healthy",))
    assert hypothesis.status is CausalHypothesisStatus.INCONCLUSIVE


def test_hypothesis_creation_cannot_precede_evidence_cutoff() -> None:
    with pytest.raises(ValueError, match="MUST NOT precede evidence cutoff"):
        build_causal_hypothesis(
            incident_id="incident-1",
            cause_ref="change-1",
            effect_ref="finding-1",
            mechanism="deployment_error",
            graph_revision="graph-1",
            evidence_cutoff=_NOW,
            method_version="causal-v1",
            evidence_grade=CausalEvidenceGrade.ASSOCIATION,
            assessment=_assessment(),
            created_at=_NOW - timedelta(seconds=1),
        )


def test_refuted_closure_demotes_evidence_grade() -> None:
    closed = close_causal_hypothesis(
        _hypothesis(),
        closure=CausalClosure.REFUTED,
        outcome_ref="outcome-1",
        created_at=_NOW + timedelta(seconds=1),
    )
    assert closed.status is CausalHypothesisStatus.REFUTED
    assert closed.evidence_grade is CausalEvidenceGrade.ASSOCIATION


def test_confirmed_closure_requires_independent_outcome_and_becomes_interventional() -> None:
    with pytest.raises(ValueError, match="outcome_ref"):
        close_causal_hypothesis(
            _hypothesis(),
            closure=CausalClosure.CONFIRMED,
            outcome_ref="",
            created_at=_NOW,
        )
    closed = close_causal_hypothesis(
        _hypothesis(),
        closure=CausalClosure.CONFIRMED,
        outcome_ref="outcome-1",
        created_at=_NOW + timedelta(seconds=1),
        interventional_evidence_ref="a" * 64,
    )
    assert closed.evidence_grade is CausalEvidenceGrade.INTERVENTIONAL
    assert closed.to_ontology_object().object_type == "CausalHypothesis"
    assert closed.to_ontology_object().properties["closure"] == "confirmed"


def test_confirmed_closure_rejects_missing_interventional_receipt() -> None:
    with pytest.raises(ValueError, match="interventional evidence"):
        close_causal_hypothesis(
            _hypothesis(),
            closure=CausalClosure.CONFIRMED,
            outcome_ref="outcome-1",
            created_at=_NOW + timedelta(seconds=1),
        )


def test_hypothesis_revision_identity_binds_evidence_and_is_order_independent() -> None:
    first = _hypothesis(supporting_refs=("event:b", "event:a"))
    reordered = _hypothesis(supporting_refs=("event:a", "event:b"))
    changed = _hypothesis(supporting_refs=("event:a",))

    assert first.hypothesis_id == reordered.hypothesis_id
    assert first.hypothesis_id != changed.hypothesis_id
    assert first.created_at == _NOW


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_assessment_rejects_invalid_scores(value: float) -> None:
    with pytest.raises(ValueError, match="finite and in"):
        _assessment(mechanism_fit=value)
