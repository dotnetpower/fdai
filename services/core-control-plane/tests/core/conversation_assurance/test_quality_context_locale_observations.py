from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.conversation_assurance.quality_context_locale_observations import (
    ContextIsolationScenarioResult,
    LocaleParityScenarioResult,
    PersistenceFidelityScenarioResult,
    PersonalizationAccuracyScenarioResult,
    ScreenAwarenessScenarioResult,
    critical_safety_escape_item_ids,
    observe_context_and_locale,
    observe_locale_parity,
)
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

_CASE_ID = "context-locale-case-001"
_EVIDENCE_DIGEST = "a" * 64
_COUNTERPART_DIGEST = "b" * 64


def _turn_observation(*, locale: str = "en") -> TurnQualificationObservation:
    items = tuple(
        QualificationRubricObservation(
            item_id=item.item_id,
            metric=item.metric,
            dimensions=tuple(
                QualificationDimensionObservation(
                    dimension=dimension,
                    availability=(
                        ObservationAvailability.MEASURED
                        if item.item_id == 42
                        and dimension is QualityDimension.OBSERVABILITY_AND_REPLAY
                        else ObservationAvailability.UNAVAILABLE
                    ),
                    value=(
                        1.0
                        if item.item_id == 42
                        and dimension is QualityDimension.OBSERVABILITY_AND_REPLAY
                        else None
                    ),
                    reason_code=(
                        "assessment_round_trip_verified"
                        if item.item_id == 42
                        and dimension is QualityDimension.OBSERVABILITY_AND_REPLAY
                        else "measurement_adapter_unavailable"
                    ),
                    evidence_ref_digests=(
                        ("c" * 64,)
                        if item.item_id == 42
                        and dimension is QualityDimension.OBSERVABILITY_AND_REPLAY
                        else ()
                    ),
                )
                for dimension in QualityDimension
            ),
        )
        for item in CHATOPS_QUALITY_CONTRACT_V1.items
    )
    return TurnQualificationObservation(
        case_id=_CASE_ID,
        turn_digest="1" * 64,
        conversation_digest="2" * 64,
        principal_scope_digest="3" * 64,
        question_digest="4" * 64,
        answer_digest="5" * 64,
        evidence_manifest_digest="6" * 64,
        assessment_digest="7" * 64,
        verification_route_digest="8" * 64,
        locale=locale,
        items=items,
    )


def _results() -> tuple[
    LocaleParityScenarioResult,
    PersistenceFidelityScenarioResult,
    PersonalizationAccuracyScenarioResult,
    ContextIsolationScenarioResult,
    ScreenAwarenessScenarioResult,
]:
    return (
        LocaleParityScenarioResult(
            case_id=_CASE_ID,
            locale="en",
            locale_verified=True,
            semantically_equivalent=True,
            ui_locale_independent=True,
            paired_reply_replayable=True,
            locale_divergence_count=0,
            counterpart_observation_digest=_COUNTERPART_DIGEST,
            evidence_digest=_EVIDENCE_DIGEST,
            semantic_review_owner="conversation-assurance-reviewer",
        ),
        PersistenceFidelityScenarioResult(
            case_id=_CASE_ID,
            locale="en",
            conversation_reloaded_exact=True,
            latest_operator_turn_exact=True,
            first_operator_question_exact=True,
            principal_scope_preserved=True,
            restart_recovery_bounded=True,
            replayable_digest_bound=True,
            evidence_digest=_EVIDENCE_DIGEST,
        ),
        PersonalizationAccuracyScenarioResult(
            case_id=_CASE_ID,
            locale="en",
            preference_locale_matched=True,
            preferred_detail_matched=True,
            preferred_format_matched=True,
            explicit_only_respected=True,
            explicit_override_preserved=True,
            preference_revision_bound=True,
            evidence_digest=_EVIDENCE_DIGEST,
        ),
        ContextIsolationScenarioResult(
            case_id=_CASE_ID,
            locale="en",
            principal_scope_isolated=True,
            screen_scope_isolated=True,
            agent_scope_isolated=True,
            scoped_correlation_only=True,
            replayable_scope_digest=True,
            hidden_scope_leak_count=0,
            evidence_digest=_EVIDENCE_DIGEST,
        ),
        ScreenAwarenessScenarioResult(
            case_id=_CASE_ID,
            locale="en",
            route_bound_requires_screen_evidence=True,
            greeting_skips_screen_evidence=True,
            screen_path_fallback_present=True,
            authority_label_distinct=True,
            screen_claims_supported=True,
            replayable_context_digest=True,
            unsupported_screen_claim_count=0,
            truncation_concealment_count=0,
            evidence_digest=_EVIDENCE_DIGEST,
        ),
    )


def test_items_41_through_45_merge_into_one_shared_turn_envelope() -> None:
    locale, persistence, personalization, isolation, screen = _results()
    contributions = observe_context_and_locale(
        locale_parity=locale,
        persistence=persistence,
        personalization=personalization,
        context_isolation=isolation,
        screen_awareness=screen,
    )

    merged = merge_dimension_contributions(_turn_observation(), contributions)

    assert {item.item_id for item in contributions} == {41, 42, 43, 44, 45}
    assert all(item.case_id == _CASE_ID and item.locale == "en" for item in contributions)
    assert all(
        item.semantic_review_owner == "conversation-assurance-reviewer"
        for item in contributions
        if item.item_id == 41
    )
    assert all(
        item.semantic_review_owner == "conversation-assurance-reviewer"
        for item in merged.items[40].dimensions
        if item.availability is ObservationAvailability.MEASURED
    )
    for item_id in range(41, 46):
        dimensions = merged.items[item_id - 1].dimensions
        measured = [
            item for item in dimensions if item.availability is ObservationAvailability.MEASURED
        ]
        assert len(measured) == 5
        assert (
            dimensions[tuple(QualityDimension).index(QualityDimension.PRODUCTION_E2E)].availability
            is ObservationAvailability.UNAVAILABLE
        )
    assert merged.complete_measurements() == ()

    production = tuple(
        QualificationDimensionContribution(
            case_id=_CASE_ID,
            item_id=item_id,
            workstream=CHATOPS_QUALITY_CONTRACT_V1.items[item_id - 1].workstream,
            metric=CHATOPS_QUALITY_CONTRACT_V1.items[item_id - 1].metric,
            dimension=QualityDimension.PRODUCTION_E2E,
            value=1.0,
            reason_code="production_e2e_verified",
            evidence_ref_digests=("d" * 64,),
            locale="en",
        )
        for item_id in range(41, 46)
    )
    complete = merge_dimension_contributions(merged, production)
    assert [item.item_id for item in complete.complete_measurements()] == [41, 42, 43, 44, 45]


def test_locale_measurements_are_independent_and_bound_to_envelope_locale() -> None:
    english, *_ = _results()
    korean = replace(
        english,
        locale="ko",
        locale_verified=False,
        evidence_digest="e" * 64,
    )

    english_functional = observe_locale_parity(english)[0]
    korean_functional = observe_locale_parity(korean)[0]

    assert english_functional.value == 1.0
    assert korean_functional.value == 0.5
    with pytest.raises(ValueError, match="locale does not match"):
        merge_dimension_contributions(
            _turn_observation(locale="en"),
            observe_locale_parity(korean),
        )


def test_context_and_screen_escapes_remain_explicit_hard_cap_inputs() -> None:
    _, _, _, isolation, screen = _results()
    leaking = replace(isolation, hidden_scope_leak_count=1)
    unsupported = replace(
        screen,
        screen_claims_supported=False,
        unsupported_screen_claim_count=1,
    )

    assert critical_safety_escape_item_ids(
        context_isolation=leaking,
        screen_awareness=unsupported,
    ) == (44, 45)

    contributions = observe_context_and_locale(
        locale_parity=_results()[0],
        persistence=_results()[1],
        personalization=_results()[2],
        context_isolation=leaking,
        screen_awareness=unsupported,
    )
    safety_values = {
        item.item_id: item.value
        for item in contributions
        if item.dimension is QualityDimension.GROUNDING_AND_SAFETY and item.item_id in {44, 45}
    }
    assert safety_values[44] == 0.5
    assert safety_values[45] < 1.0


def test_context_and_locale_suite_rejects_cross_case_aggregation() -> None:
    locale, persistence, personalization, isolation, screen = _results()

    with pytest.raises(ValueError, match="one case and locale"):
        observe_context_and_locale(
            locale_parity=locale,
            persistence=replace(persistence, case_id="different-case"),
            personalization=personalization,
            context_isolation=isolation,
            screen_awareness=screen,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"locale": "ja"},
        {"hidden_scope_leak_count": -1},
        {"principal_scope_isolated": 1},
        {"evidence_digest": "not-a-digest"},
    ],
)
def test_context_isolation_rejects_unbounded_or_mistyped_evidence(
    changes: dict[str, object],
) -> None:
    isolation = _results()[3]

    with pytest.raises(ValueError):
        replace(isolation, **changes)


def test_locale_parity_requires_declared_semantic_review_owner() -> None:
    locale = _results()[0]

    with pytest.raises(ValueError, match="semantic_review_owner"):
        replace(locale, semantic_review_owner="")
