from __future__ import annotations

import pytest
from fdai.core.conversation_assurance import (
    COMMON_CHANNEL_CRITERIA,
    ChannelAssuranceProfile,
    ChannelCriterionObservation,
    ChannelPresentationCriterion,
    assess_channel_presentation,
)


def _passing_common_observations() -> tuple[ChannelCriterionObservation, ...]:
    return tuple(
        ChannelCriterionObservation(
            criterion=criterion,
            passed=True,
            reason_code="verified_projection",
        )
        for criterion in ChannelPresentationCriterion
        if criterion in COMMON_CHANNEL_CRITERIA
    )


def test_unsupported_channel_features_are_neutral() -> None:
    profile = ChannelAssuranceProfile(
        profile_id="custom-text-v1",
        channel_kind="custom",
    )

    assessment = assess_channel_presentation(
        profile=profile,
        observations=_passing_common_observations(),
    )

    assert assessment.score == 4
    assert assessment.max_score == 4
    assert assessment.presentation_passed
    assert all(
        result.score is None
        for result in assessment.results
        if result.criterion not in COMMON_CHANNEL_CRITERIA
    )


def test_supported_channel_feature_requires_measurement() -> None:
    profile = ChannelAssuranceProfile(
        profile_id="web-console-v1",
        channel_kind="web",
        supported_optional_criteria=frozenset(
            {
                ChannelPresentationCriterion.PREPARING_STATUS,
                ChannelPresentationCriterion.ACTIVITY_RECORDS,
            }
        ),
    )

    assessment = assess_channel_presentation(
        profile=profile,
        observations=_passing_common_observations(),
    )

    assert not assessment.presentation_passed
    assert tuple(result.reason_code for result in assessment.results if result.score == 0) == (
        "channel_measurement_missing",
        "channel_measurement_missing",
    )


def test_common_failure_cannot_be_hidden_by_optional_channel_features() -> None:
    profile = ChannelAssuranceProfile(
        profile_id="teams-card-v1",
        channel_kind="teams",
        supported_optional_criteria=frozenset(
            criterion
            for criterion in ChannelPresentationCriterion
            if criterion not in COMMON_CHANNEL_CRITERIA
        ),
    )
    observations = tuple(
        ChannelCriterionObservation(
            criterion=criterion,
            passed=criterion is not ChannelPresentationCriterion.EVIDENCE,
            reason_code="measured",
        )
        for criterion in ChannelPresentationCriterion
    )

    assessment = assess_channel_presentation(profile=profile, observations=observations)

    assert assessment.score == 9
    assert assessment.max_score == 10
    assert assessment.mandatory_failures == (ChannelPresentationCriterion.EVIDENCE,)
    assert not assessment.presentation_passed


def test_custom_profile_rejects_measurement_for_unsupported_feature() -> None:
    profile = ChannelAssuranceProfile(
        profile_id="direct-line-text-v1",
        channel_kind="direct-line",
    )
    observations = (
        *_passing_common_observations(),
        ChannelCriterionObservation(
            criterion=ChannelPresentationCriterion.PROGRESS_UPDATES,
            passed=True,
            reason_code="observed",
        ),
    )

    with pytest.raises(ValueError, match="does not support"):
        assess_channel_presentation(profile=profile, observations=observations)
