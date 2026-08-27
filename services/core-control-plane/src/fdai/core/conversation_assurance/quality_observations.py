"""Bounded qualification observations derived from completed-turn assurance evidence."""

from __future__ import annotations

import hashlib
from dataclasses import replace

from fdai.core.conversation_assurance.models import (
    AssessmentRecord,
    AssuranceCriterion,
    AssuranceVerdict,
    CriterionScore,
    TurnAssessmentInput,
)
from fdai.core.conversation_assurance.quality_observation_models import (
    ObservationAvailability,
    QualificationDimensionContribution,
    QualificationDimensionObservation,
    QualificationRubricObservation,
    TurnQualificationObservation,
)
from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    QualityDimension,
)

_UNAVAILABLE_AUTHORITY = frozenset({"none", "unknown", "unavailable", "unverified"})


def observe_completed_turn(
    *,
    case_id: str,
    turn: TurnAssessmentInput,
    assessment: AssessmentRecord,
) -> TurnQualificationObservation:
    """Map existing turn evidence without treating absent metrics as successful."""

    _validate_record_linkage(turn, assessment)
    items = _empty_items()
    criteria = assessment.decision.criteria
    if len({score.criterion for score in criteria}) != len(criteria):
        raise ValueError("assessment criteria MUST be unique")
    semantic_scores = {score.criterion: score for score in criteria}
    independent_review = (
        assessment.decision.model_calls >= 2
        and len(set(assessment.decision.evaluator_identities)) >= 2
    )
    if independent_review:
        items = _set_semantic_score(
            items,
            item_id=6,
            score=semantic_scores.get(AssuranceCriterion.CLARITY),
        )
        items = _set_semantic_score(
            items,
            item_id=9,
            score=semantic_scores.get(AssuranceCriterion.INTENT_RESOLUTION),
        )
        items = _set_semantic_score(
            items,
            item_id=10,
            score=semantic_scores.get(AssuranceCriterion.CALIBRATION),
        )
        items = _set_semantic_score(
            items,
            item_id=11,
            score=semantic_scores.get(AssuranceCriterion.FACTUAL_CORRECTNESS),
            dimension=QualityDimension.GROUNDING_AND_SAFETY,
        )

    deterministic_grounding = _deterministic_grounding(turn, assessment)
    if deterministic_grounding is not None:
        grounding_refs = turn.evidence_refs or turn.failed_claim_ids or assessment.decision.reasons
        items = _set_dimension(
            items,
            item_id=11,
            dimension=QualityDimension.GROUNDING_AND_SAFETY,
            value=deterministic_grounding,
            reason_code="terminal_grounding_verdict",
            evidence_refs=grounding_refs,
        )

    atomic_claim_support = _atomic_claim_support(turn)
    atomic_refs = turn.failed_claim_ids or turn.evidence_refs
    if atomic_claim_support is not None and not atomic_refs:
        atomic_claim_support = None
    if atomic_claim_support is not None:
        items = _set_dimension(
            items,
            item_id=13,
            dimension=QualityDimension.GROUNDING_AND_SAFETY,
            value=atomic_claim_support,
            reason_code="terminal_atomic_claim_check",
            evidence_refs=atomic_refs,
        )

    items = _set_dimension(
        items,
        item_id=42,
        dimension=QualityDimension.OBSERVABILITY_AND_REPLAY,
        value=1.0,
        reason_code="assessment_round_trip_verified",
        evidence_refs=(assessment.assessment_id,),
    )
    items = _set_unavailable_reason(
        items,
        item_id=41,
        reason_code="cross_locale_aggregate_required",
    )
    return TurnQualificationObservation(
        case_id=case_id,
        turn_digest=_digest(turn.turn_id),
        conversation_digest=_digest(turn.conversation_id),
        principal_scope_digest=_digest(turn.principal_scope),
        question_digest=_require_digest(turn.question_digest, "question_digest"),
        answer_digest=_require_digest(turn.answer_digest, "answer_digest"),
        evidence_manifest_digest=_require_digest(
            turn.evidence_manifest_digest,
            "evidence_manifest_digest",
        ),
        assessment_digest=_digest(assessment.assessment_id),
        verification_route_digest=(
            None if turn.verification_route_id is None else _digest(turn.verification_route_id)
        ),
        locale=turn.locale,
        items=items,
    )


def _empty_items() -> tuple[QualificationRubricObservation, ...]:
    return tuple(
        QualificationRubricObservation(
            item_id=item.item_id,
            metric=item.metric,
            dimensions=tuple(
                QualificationDimensionObservation(
                    dimension=dimension,
                    availability=ObservationAvailability.UNAVAILABLE,
                    value=None,
                    reason_code="measurement_adapter_unavailable",
                )
                for dimension in QualityDimension
            ),
        )
        for item in CHATOPS_QUALITY_CONTRACT_V1.items
    )


def _set_semantic_score(
    items: tuple[QualificationRubricObservation, ...],
    *,
    item_id: int,
    score: CriterionScore | None,
    dimension: QualityDimension = QualityDimension.FUNCTIONAL_CORRECTNESS,
) -> tuple[QualificationRubricObservation, ...]:
    if score is None or not score.evidence_refs:
        return _set_unavailable_reason(
            items,
            item_id=item_id,
            reason_code=(
                "semantic_criterion_unavailable"
                if score is None
                else "semantic_evidence_ref_unavailable"
            ),
        )
    return _set_dimension(
        items,
        item_id=item_id,
        dimension=dimension,
        value=score.score / 4.0,
        reason_code=f"semantic_criterion:{score.criterion.value}",
        evidence_refs=score.evidence_refs,
    )


def _set_dimension(
    items: tuple[QualificationRubricObservation, ...],
    *,
    item_id: int,
    dimension: QualityDimension,
    value: float,
    reason_code: str,
    evidence_refs: tuple[str, ...],
) -> tuple[QualificationRubricObservation, ...]:
    if not evidence_refs:
        raise ValueError("measured qualification dimension MUST cite evidence")
    index = item_id - 1
    item = items[index]
    dimensions = tuple(
        QualificationDimensionObservation(
            dimension=existing.dimension,
            availability=ObservationAvailability.MEASURED,
            value=value,
            reason_code=reason_code,
            evidence_ref_digests=tuple(_digest(reference) for reference in evidence_refs),
        )
        if existing.dimension is dimension
        else existing
        for existing in item.dimensions
    )
    return items[:index] + (replace(item, dimensions=dimensions),) + items[index + 1 :]


def merge_dimension_contributions(
    observation: TurnQualificationObservation,
    contributions: tuple[QualificationDimensionContribution, ...],
) -> TurnQualificationObservation:
    """Fill unavailable slots without allowing cross-case or conflicting evidence."""

    keys = tuple((item.item_id, item.dimension) for item in contributions)
    if len(keys) != len(set(keys)):
        raise ValueError("qualification contributions MUST be unique by item and dimension")
    items = observation.items
    for contribution in contributions:
        if contribution.case_id != observation.case_id:
            raise ValueError("qualification contribution case_id does not match the observation")
        if contribution.locale is not None and contribution.locale != observation.locale:
            raise ValueError("qualification contribution locale does not match the observation")
        item_index = contribution.item_id - 1
        item = items[item_index]
        dimension_index = tuple(QualityDimension).index(contribution.dimension)
        existing = item.dimensions[dimension_index]
        if existing.availability is ObservationAvailability.MEASURED:
            raise ValueError("qualification contribution MUST NOT overwrite measured evidence")
        dimensions = (
            item.dimensions[:dimension_index]
            + (
                QualificationDimensionObservation(
                    dimension=contribution.dimension,
                    availability=ObservationAvailability.MEASURED,
                    value=contribution.value,
                    reason_code=contribution.reason_code,
                    evidence_ref_digests=contribution.evidence_ref_digests,
                    semantic_review_owner=contribution.semantic_review_owner,
                ),
            )
            + item.dimensions[dimension_index + 1 :]
        )
        items = (
            items[:item_index] + (replace(item, dimensions=dimensions),) + items[item_index + 1 :]
        )
    return replace(observation, items=items)


def _set_unavailable_reason(
    items: tuple[QualificationRubricObservation, ...],
    *,
    item_id: int,
    reason_code: str,
) -> tuple[QualificationRubricObservation, ...]:
    index = item_id - 1
    item = items[index]
    dimensions = tuple(
        replace(dimension, reason_code=reason_code)
        if dimension.availability is ObservationAvailability.UNAVAILABLE
        else dimension
        for dimension in item.dimensions
    )
    return items[:index] + (replace(item, dimensions=dimensions),) + items[index + 1 :]


def _deterministic_grounding(
    turn: TurnAssessmentInput,
    assessment: AssessmentRecord,
) -> float | None:
    if not turn.deterministic_answer:
        return None
    if assessment.decision.verdict is AssuranceVerdict.FAIL:
        return 0.0
    if (
        assessment.decision.verdict is AssuranceVerdict.PASS
        and turn.evidence_complete is not False
        and turn.evidence_refs
        and turn.verification_authority.casefold() not in _UNAVAILABLE_AUTHORITY
        and turn.checks_total > 0
        and turn.checks_completed == turn.checks_total
    ):
        return 1.0
    return None


def _atomic_claim_support(turn: TurnAssessmentInput) -> float | None:
    if turn.failed_claim_ids:
        return 0.0
    if turn.checks_total > 0 and turn.checks_completed == turn.checks_total:
        return 1.0
    return None


def _validate_record_linkage(
    turn: TurnAssessmentInput,
    assessment: AssessmentRecord,
) -> None:
    expected = (
        turn.turn_id,
        turn.conversation_id,
        turn.principal_scope,
        turn.question_digest,
        turn.answer_digest,
        turn.evidence_manifest_digest,
    )
    actual = (
        assessment.turn_id,
        assessment.conversation_id,
        assessment.principal_scope,
        assessment.question_digest,
        assessment.answer_digest,
        assessment.evidence_manifest_digest,
    )
    if actual != expected:
        raise ValueError("assessment does not match the completed turn")


def _require_digest(value: str, field: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} MUST be a lowercase SHA-256 digest")
    return value


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = [
    "ObservationAvailability",
    "QualificationDimensionObservation",
    "QualificationRubricObservation",
    "TurnQualificationObservation",
    "merge_dimension_contributions",
    "observe_completed_turn",
]
