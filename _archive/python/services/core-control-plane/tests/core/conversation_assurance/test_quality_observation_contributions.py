"""Tests for merging evidence-owner contributions into quality observations."""

from __future__ import annotations

import pytest
from fdai.core.conversation_assurance.quality_observation_models import (
    ObservationAvailability,
    QualificationDimensionContribution,
    QualificationDimensionObservation,
    QualificationRubricObservation,
    TurnQualificationObservation,
)
from fdai.core.conversation_assurance.quality_observations import (
    merge_dimension_contributions,
)
from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    QualityDimension,
)


def _observation(*, measured_item: int | None = None) -> TurnQualificationObservation:
    items = tuple(
        QualificationRubricObservation(
            item_id=item.item_id,
            metric=item.metric,
            dimensions=tuple(
                QualificationDimensionObservation(
                    dimension=dimension,
                    availability=(
                        ObservationAvailability.MEASURED
                        if item.item_id == measured_item
                        and dimension is QualityDimension.FUNCTIONAL_CORRECTNESS
                        else ObservationAvailability.UNAVAILABLE
                    ),
                    value=(
                        1.0
                        if item.item_id == measured_item
                        and dimension is QualityDimension.FUNCTIONAL_CORRECTNESS
                        else None
                    ),
                    reason_code="existing_measurement",
                    evidence_ref_digests=(
                        ("b" * 64,)
                        if item.item_id == measured_item
                        and dimension is QualityDimension.FUNCTIONAL_CORRECTNESS
                        else ()
                    ),
                )
                for dimension in QualityDimension
            ),
        )
        for item in CHATOPS_QUALITY_CONTRACT_V1.items
    )
    return TurnQualificationObservation(
        case_id="en-case-001",
        turn_digest="1" * 64,
        conversation_digest="2" * 64,
        principal_scope_digest="3" * 64,
        question_digest="4" * 64,
        answer_digest="5" * 64,
        evidence_manifest_digest="6" * 64,
        assessment_digest="7" * 64,
        verification_route_digest="8" * 64,
        locale="en",
        items=items,
    )


def _contribution(
    *,
    item_id: int = 1,
    dimension: QualityDimension = QualityDimension.FUNCTIONAL_CORRECTNESS,
    case_id: str = "en-case-001",
    locale: str | None = None,
) -> QualificationDimensionContribution:
    item = CHATOPS_QUALITY_CONTRACT_V1.items[item_id - 1]
    return QualificationDimensionContribution(
        case_id=case_id,
        item_id=item_id,
        workstream=item.workstream,
        metric=item.metric,
        dimension=dimension,
        value=0.98,
        reason_code="owner_measurement",
        evidence_ref_digests=("a" * 64,),
        locale=locale,
    )


def test_owner_contributions_fill_only_unavailable_dimensions() -> None:
    observation = _observation()
    contributions = tuple(
        _contribution(item_id=1, dimension=dimension) for dimension in QualityDimension
    )

    merged = merge_dimension_contributions(observation, contributions)

    measurements = merged.complete_measurements()
    assert len(measurements) == 1
    assert measurements[0].item_id == 1
    assert dict(measurements[0].components) == {dimension: 0.98 for dimension in QualityDimension}
    assert merged.to_dict()["content_digest"] != observation.to_dict()["content_digest"]


def test_contributions_reject_case_conflicts_duplicates_and_overwrites() -> None:
    observation = _observation(measured_item=6)
    contribution = _contribution()

    with pytest.raises(ValueError, match="case_id does not match"):
        merge_dimension_contributions(
            observation,
            (_contribution(case_id="en-case-002"),),
        )
    with pytest.raises(ValueError, match="locale does not match"):
        merge_dimension_contributions(
            observation,
            (_contribution(locale="ko"),),
        )
    with pytest.raises(ValueError, match="unique by item and dimension"):
        merge_dimension_contributions(observation, (contribution, contribution))
    with pytest.raises(ValueError, match="MUST NOT overwrite"):
        merge_dimension_contributions(
            observation,
            (
                _contribution(
                    item_id=6,
                    dimension=QualityDimension.FUNCTIONAL_CORRECTNESS,
                ),
            ),
        )


def test_contribution_requires_contract_owner_and_evidence_commitment() -> None:
    with pytest.raises(ValueError, match="workstream and metric"):
        QualificationDimensionContribution(
            case_id="en-case-001",
            item_id=1,
            workstream="sre_reasoning",
            metric="intent_accuracy",
            dimension=QualityDimension.FUNCTIONAL_CORRECTNESS,
            value=0.98,
            reason_code="owner_measurement",
            evidence_ref_digests=("a" * 64,),
        )
    with pytest.raises(ValueError, match="cite evidence"):
        QualificationDimensionContribution(
            case_id="en-case-001",
            item_id=1,
            workstream="intent_and_planning",
            metric="intent_accuracy",
            dimension=QualityDimension.FUNCTIONAL_CORRECTNESS,
            value=0.98,
            reason_code="owner_measurement",
            evidence_ref_digests=(),
        )
    with pytest.raises(ValueError, match="semantic_review_owner"):
        QualificationDimensionContribution(
            case_id="en-case-001",
            item_id=1,
            workstream="intent_and_planning",
            metric="intent_accuracy",
            dimension=QualityDimension.FUNCTIONAL_CORRECTNESS,
            value=0.98,
            reason_code="owner_measurement",
            evidence_ref_digests=("a" * 64,),
            semantic_review_owner="not portable",
        )
