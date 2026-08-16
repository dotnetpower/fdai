from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.rca.hypothesis import (
    CausalActionMode,
    CausalClosure,
    CausalEvidenceAssessment,
    CausalHypothesisStatus,
    build_causal_hypothesis,
    causal_action_mode,
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


def _graded_hypothesis(grade: CausalEvidenceGrade, **assessment: object):  # type: ignore[no-untyped-def]
    return build_causal_hypothesis(
        incident_id="incident-1",
        cause_ref="change-1",
        effect_ref="finding-1",
        mechanism="deployment_error",
        graph_revision="graph-1",
        evidence_cutoff=_NOW,
        method_version="causal-v1",
        evidence_grade=grade,
        assessment=_assessment(**assessment),
        created_at=_NOW,
    )


def test_unsafe_closure_demotes_grade_and_keeps_the_action_in_shadow() -> None:
    supported = _graded_hypothesis(CausalEvidenceGrade.QUASI_EXPERIMENTAL)
    assert causal_action_mode(supported) is CausalActionMode.GATED

    closed = close_causal_hypothesis(
        supported,
        closure=CausalClosure.UNSAFE,
        outcome_ref="outcome-unsafe",
        created_at=_NOW + timedelta(seconds=1),
    )

    assert closed.closure is CausalClosure.UNSAFE
    assert closed.evidence_grade is CausalEvidenceGrade.ASSOCIATION
    assert closed.hypothesis_id != supported.hypothesis_id
    assert causal_action_mode(closed) is CausalActionMode.SHADOW


def test_refuted_closure_demotes_grade_and_keeps_the_action_in_shadow() -> None:
    closed = close_causal_hypothesis(
        _graded_hypothesis(CausalEvidenceGrade.INTERVENTIONAL),
        closure=CausalClosure.REFUTED,
        outcome_ref="outcome-refuted",
        created_at=_NOW + timedelta(seconds=1),
    )

    assert closed.evidence_grade is CausalEvidenceGrade.ASSOCIATION
    assert causal_action_mode(closed) is CausalActionMode.SHADOW


def test_inconclusive_closure_never_raises_the_grade_and_stays_in_shadow() -> None:
    closed = close_causal_hypothesis(
        _graded_hypothesis(CausalEvidenceGrade.QUASI_EXPERIMENTAL),
        closure=CausalClosure.INCONCLUSIVE,
        outcome_ref="outcome-inconclusive",
        created_at=_NOW + timedelta(seconds=1),
    )

    assert closed.evidence_grade is CausalEvidenceGrade.QUASI_EXPERIMENTAL
    assert causal_action_mode(closed) is CausalActionMode.SHADOW


def test_refuting_evidence_keeps_a_high_grade_revision_in_shadow() -> None:
    contested = _graded_hypothesis(
        CausalEvidenceGrade.INTERVENTIONAL,
        refuting_refs=("metric:healthy",),
    )

    assert contested.status is CausalHypothesisStatus.INCONCLUSIVE
    assert causal_action_mode(contested) is CausalActionMode.SHADOW


def test_weak_grades_and_open_candidates_stay_in_shadow() -> None:
    weak = _graded_hypothesis(CausalEvidenceGrade.PREDICTIVE_PRECEDENCE)
    candidate = _graded_hypothesis(
        CausalEvidenceGrade.QUASI_EXPERIMENTAL,
        supporting_refs=(),
    )

    assert causal_action_mode(weak) is CausalActionMode.SHADOW
    assert candidate.status is CausalHypothesisStatus.CANDIDATE
    assert causal_action_mode(candidate) is CausalActionMode.SHADOW


def test_confirmed_interventional_closure_is_gated_evidence_only() -> None:
    closed = close_causal_hypothesis(
        _graded_hypothesis(CausalEvidenceGrade.PREDICTIVE_PRECEDENCE),
        closure=CausalClosure.CONFIRMED,
        outcome_ref="outcome-confirmed",
        created_at=_NOW + timedelta(seconds=1),
        interventional_evidence_ref="b" * 64,
    )

    assert closed.evidence_grade is CausalEvidenceGrade.INTERVENTIONAL
    assert causal_action_mode(closed) is CausalActionMode.GATED
