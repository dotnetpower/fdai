from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fdai.core.conversation_assurance.models import (
    AssessmentRecord,
    AssuranceCriterion,
    AssuranceDecision,
    AssuranceVerdict,
    CriterionScore,
    TurnAssessmentInput,
)
from fdai.core.conversation_assurance.quality_observations import (
    ObservationAvailability,
    QualificationDimensionObservation,
    observe_completed_turn,
)
from fdai.core.conversation_assurance.quality_scorecard import QualityDimension


def _turn(**overrides: object) -> TurnAssessmentInput:
    values: dict[str, object] = {
        "turn_id": "turn-1",
        "conversation_id": "conversation-1",
        "principal_scope": "principal-scope",
        "question": "What changed?",
        "answer": "One verified resource changed.",
        "question_digest": "1" * 64,
        "answer_digest": "2" * 64,
        "evidence_manifest_digest": "3" * 64,
        "evidence_refs": ("evidence:1",),
        "verification_status": "verified",
        "verification_authority": "server_inventory_graph",
        "checks_completed": 1,
        "checks_total": 1,
        "verification_route_id": "route-1",
        "evidence_complete": True,
        "locale": "en",
    }
    values.update(overrides)
    return TurnAssessmentInput(**values)  # type: ignore[arg-type]


def _criteria(value: int = 4) -> tuple[CriterionScore, ...]:
    return tuple(
        CriterionScore(
            criterion=criterion,
            score=value,
            rationale="Supported by the supplied evidence.",
            evidence_refs=("evidence:1",),
        )
        for criterion in AssuranceCriterion
    )


def _assessment(
    turn: TurnAssessmentInput,
    *,
    decision: AssuranceDecision | None = None,
    **overrides: object,
) -> AssessmentRecord:
    values: dict[str, object] = {
        "assessment_id": "assessment-1",
        "turn_id": turn.turn_id,
        "conversation_id": turn.conversation_id,
        "principal_scope": turn.principal_scope,
        "question_digest": turn.question_digest,
        "answer_digest": turn.answer_digest,
        "evidence_manifest_digest": turn.evidence_manifest_digest,
        "rubric_version": "1.0.0",
        "model_set_digest": "model-set",
        "decision": decision
        or AssuranceDecision(
            verdict=AssuranceVerdict.PASS,
            content_score=100.0,
            confidence=1.0,
            criteria=_criteria(),
            evaluator_identities=("model-a", "model-b"),
            model_calls=2,
        ),
        "assessed_at": datetime(2026, 8, 27, tzinfo=UTC),
    }
    values.update(overrides)
    return AssessmentRecord(**values)  # type: ignore[arg-type]


def _dimension(
    observation: object,
    item_id: int,
    dimension: QualityDimension,
) -> QualificationDimensionObservation:
    item = observation.items[item_id - 1]  # type: ignore[attr-defined]
    return item.dimensions[tuple(QualityDimension).index(dimension)]


def test_emits_all_50_items_and_all_six_dimensions_without_raw_identity() -> None:
    turn = _turn()
    observation = observe_completed_turn(
        case_id="en-case-001",
        turn=turn,
        assessment=_assessment(turn),
    )

    assert tuple(item.item_id for item in observation.items) == tuple(range(1, 51))
    assert all(
        tuple(value.dimension for value in item.dimensions) == tuple(QualityDimension)
        for item in observation.items
    )
    assert observation.turn_digest != turn.turn_id
    assert observation.conversation_digest != turn.conversation_id
    assert observation.principal_scope_digest != turn.principal_scope
    assert observation.verification_route_digest is not None
    assert (
        _dimension(
            observation,
            11,
            QualityDimension.GROUNDING_AND_SAFETY,
        ).evidence_ref_digests
        != turn.evidence_refs
    )
    assert len(observation.complete_measurements()) == 0
    first = observation.to_dict()
    assert first == observation.to_dict()
    assert first["schema_version"] == "1.1.0"
    assert first["qualification_authority"] is False
    assert len(first["content_digest"]) == 64  # type: ignore[arg-type]
    serialized = json.dumps(first)
    assert turn.turn_id not in serialized
    assert turn.conversation_id not in serialized
    assert turn.principal_scope not in serialized
    assert turn.evidence_refs[0] not in serialized


def test_maps_independently_reviewed_semantic_criteria_without_filling_other_dimensions() -> None:
    turn = _turn()
    observation = observe_completed_turn(
        case_id="en-case-001",
        turn=turn,
        assessment=_assessment(turn),
    )

    clarity = _dimension(
        observation,
        6,
        QualityDimension.FUNCTIONAL_CORRECTNESS,
    )
    relevance = _dimension(
        observation,
        9,
        QualityDimension.FUNCTIONAL_CORRECTNESS,
    )
    calibration = _dimension(
        observation,
        10,
        QualityDimension.FUNCTIONAL_CORRECTNESS,
    )
    grounding = _dimension(
        observation,
        11,
        QualityDimension.GROUNDING_AND_SAFETY,
    )
    assert clarity.value == relevance.value == calibration.value == grounding.value == 1.0
    assert clarity.availability is ObservationAvailability.MEASURED
    assert (
        _dimension(
            observation,
            6,
            QualityDimension.PRODUCTION_E2E,
        ).availability
        is ObservationAvailability.UNAVAILABLE
    )


def test_semantic_scores_without_two_independent_evaluators_remain_unavailable() -> None:
    turn = _turn()
    decision = AssuranceDecision(
        verdict=AssuranceVerdict.PASS,
        content_score=100.0,
        confidence=1.0,
        criteria=_criteria(),
        evaluator_identities=("model-a",),
        model_calls=1,
    )

    observation = observe_completed_turn(
        case_id="en-case-001",
        turn=turn,
        assessment=_assessment(turn, decision=decision),
    )

    assert (
        _dimension(
            observation,
            6,
            QualityDimension.FUNCTIONAL_CORRECTNESS,
        ).availability
        is ObservationAvailability.UNAVAILABLE
    )


def test_semantic_score_without_evidence_reference_remains_unavailable() -> None:
    turn = _turn()
    criteria = tuple(
        CriterionScore(
            criterion=criterion,
            score=4,
            rationale="Reviewed independently.",
        )
        for criterion in AssuranceCriterion
    )
    decision = AssuranceDecision(
        verdict=AssuranceVerdict.PASS,
        content_score=100.0,
        confidence=1.0,
        criteria=criteria,
        evaluator_identities=("model-a", "model-b"),
        model_calls=2,
    )

    observation = observe_completed_turn(
        case_id="en-case-001",
        turn=turn,
        assessment=_assessment(turn, decision=decision),
    )

    dimension = _dimension(
        observation,
        6,
        QualityDimension.FUNCTIONAL_CORRECTNESS,
    )
    assert dimension.availability is ObservationAvailability.UNAVAILABLE
    assert dimension.reason_code == "semantic_evidence_ref_unavailable"


def test_deterministic_terminal_evidence_maps_grounding_and_atomic_claim_support() -> None:
    turn = _turn(deterministic_answer=True)
    decision = AssuranceDecision(
        verdict=AssuranceVerdict.PASS,
        content_score=100.0,
        confidence=1.0,
        reasons=("deterministic_answer_verified",),
    )

    observation = observe_completed_turn(
        case_id="en-case-001",
        turn=turn,
        assessment=_assessment(turn, decision=decision),
    )

    assert (
        _dimension(
            observation,
            11,
            QualityDimension.GROUNDING_AND_SAFETY,
        ).value
        == 1.0
    )
    assert (
        _dimension(
            observation,
            13,
            QualityDimension.GROUNDING_AND_SAFETY,
        ).value
        == 1.0
    )


def test_failed_atomic_claim_is_measured_as_zero() -> None:
    turn = _turn(failed_claim_ids=("claim-1",))
    observation = observe_completed_turn(
        case_id="en-case-001",
        turn=turn,
        assessment=_assessment(turn),
    )

    assert (
        _dimension(
            observation,
            13,
            QualityDimension.GROUNDING_AND_SAFETY,
        ).value
        == 0.0
    )


def test_incomplete_or_unavailable_evidence_never_becomes_a_grounding_pass() -> None:
    turn = _turn(
        deterministic_answer=True,
        evidence_refs=(),
        evidence_complete=False,
        verification_authority="unavailable",
        checks_completed=0,
    )
    decision = AssuranceDecision(
        verdict=AssuranceVerdict.INCONCLUSIVE,
        content_score=0.0,
        confidence=0.0,
        reasons=("evidence_manifest_empty",),
    )

    observation = observe_completed_turn(
        case_id="en-case-001",
        turn=turn,
        assessment=_assessment(turn, decision=decision),
    )

    assert (
        _dimension(
            observation,
            11,
            QualityDimension.GROUNDING_AND_SAFETY,
        ).availability
        is ObservationAvailability.UNAVAILABLE
    )
    assert (
        _dimension(
            observation,
            13,
            QualityDimension.GROUNDING_AND_SAFETY,
        ).availability
        is ObservationAvailability.UNAVAILABLE
    )


def test_record_linkage_mismatch_fails_closed() -> None:
    turn = _turn()
    assessment = _assessment(turn, answer_digest="4" * 64)

    with pytest.raises(ValueError, match="does not match"):
        observe_completed_turn(
            case_id="en-case-001",
            turn=turn,
            assessment=assessment,
        )


def test_duplicate_semantic_criteria_fail_closed() -> None:
    turn = _turn()
    criteria = _criteria()
    decision = AssuranceDecision(
        verdict=AssuranceVerdict.PASS,
        content_score=100.0,
        confidence=1.0,
        criteria=criteria + (criteria[0],),
        evaluator_identities=("model-a", "model-b"),
        model_calls=2,
    )

    with pytest.raises(ValueError, match="criteria MUST be unique"):
        observe_completed_turn(
            case_id="en-case-001",
            turn=turn,
            assessment=_assessment(turn, decision=decision),
        )


def test_locale_parity_requires_cross_locale_aggregation_and_round_trip_is_measured() -> None:
    turn = _turn(locale="ko")
    observation = observe_completed_turn(
        case_id="ko-case-001",
        turn=turn,
        assessment=_assessment(turn),
    )

    locale = _dimension(
        observation,
        41,
        QualityDimension.FUNCTIONAL_CORRECTNESS,
    )
    replay = _dimension(
        observation,
        42,
        QualityDimension.OBSERVABILITY_AND_REPLAY,
    )
    assert locale.availability is ObservationAvailability.UNAVAILABLE
    assert locale.reason_code == "cross_locale_aggregate_required"
    assert replay.value == 1.0


@pytest.mark.parametrize(
    ("availability", "value"),
    [
        (ObservationAvailability.MEASURED, None),
        (ObservationAvailability.MEASURED, 1.1),
        (ObservationAvailability.UNAVAILABLE, 0.0),
    ],
)
def test_dimension_observation_rejects_inconsistent_availability(
    availability: ObservationAvailability,
    value: float | None,
) -> None:
    with pytest.raises(ValueError):
        QualificationDimensionObservation(
            dimension=QualityDimension.FUNCTIONAL_CORRECTNESS,
            availability=availability,
            value=value,
            reason_code="test",
        )
