from __future__ import annotations

import pytest
from fdai.core.conversation_assurance import (
    CHATOPS_QUALITY_CONTRACT_V1,
    ContextIsolationObservation,
    ContextLocaleScorecardEvidence,
    ContextLocaleScorecardItem,
    LocaleParityObservation,
    PersistenceFidelityObservation,
    PersonalizationAccuracyObservation,
    QualityDimension,
    QualityHardCap,
    ScorecardObservationEnvelope,
    ScreenAwarenessObservation,
    measure_context_isolation,
    measure_english_korean_parity,
    measure_persistence_fidelity,
    measure_screen_awareness,
    score_context_and_locale_suite,
    score_quality_item,
)

SOURCE_REVISION = "a" * 40


def _envelope(item: ContextLocaleScorecardItem) -> ScorecardObservationEnvelope:
    return ScorecardObservationEnvelope(
        item=item,
        case_id=f"{item.value}:case",
        principal_scope="scope:principal-a",
        source_revision=SOURCE_REVISION,
        provenance_refs=(f"proof:{item.value}",),
        correlation_refs=(f"corr:{item.value}",),
    )


def _evidence(
    *,
    frozen_hidden_corpus_present: bool = True,
    production_e2e_present: bool = True,
    latency_slo_trace_present: bool = True,
) -> ContextLocaleScorecardEvidence:
    return ContextLocaleScorecardEvidence(
        frozen_hidden_corpus_present=frozen_hidden_corpus_present,
        production_e2e_present=production_e2e_present,
        latency_slo_trace_present=latency_slo_trace_present,
    )


def test_context_and_locale_suite_scores_items_41_through_45() -> None:
    scores = score_context_and_locale_suite(
        evidence=_evidence(),
        locale_parity=LocaleParityObservation(
            envelope=_envelope(ContextLocaleScorecardItem.ENGLISH_KOREAN_PARITY),
            english_verified=True,
            korean_verified=True,
            ui_locale_independent=True,
            paired_reply_replayable=True,
        ),
        persistence=PersistenceFidelityObservation(
            envelope=_envelope(ContextLocaleScorecardItem.PERSISTENCE),
            conversation_reloaded_exact=True,
            latest_operator_turn_exact=True,
            first_operator_question_exact=True,
            principal_scope_preserved=True,
            restart_recovery_bounded=True,
            replayable_digest_bound=True,
        ),
        personalization=PersonalizationAccuracyObservation(
            envelope=_envelope(ContextLocaleScorecardItem.PERSONALIZATION),
            preference_locale_matched=True,
            preferred_detail_matched=True,
            preferred_format_matched=True,
            explicit_only_respected=True,
            explicit_override_preserved=True,
            preference_revision_bound=True,
        ),
        context_isolation=ContextIsolationObservation(
            envelope=_envelope(ContextLocaleScorecardItem.CONTEXT_ISOLATION),
            principal_scope_isolated=True,
            screen_scope_isolated=True,
            agent_scope_isolated=True,
            scoped_correlation_only=True,
            replayable_scope_digest=True,
        ),
        screen_awareness=ScreenAwarenessObservation(
            envelope=_envelope(ContextLocaleScorecardItem.SCREEN_AWARENESS),
            route_bound_requires_screen_evidence=True,
            greeting_skips_screen_evidence=True,
            screen_path_fallback_present=True,
            authority_label_distinct=True,
            screen_claims_supported=True,
            replayable_context_digest=True,
        ),
    )

    assert [score.item_id for score in scores] == [41, 42, 43, 44, 45]
    assert all(score.final_score == 10.0 for score in scores)
    assert all(score.passed is True for score in scores)


def test_locale_parity_fails_closed_without_korean_verification() -> None:
    measurement = measure_english_korean_parity(
        LocaleParityObservation(
            envelope=_envelope(ContextLocaleScorecardItem.ENGLISH_KOREAN_PARITY),
            english_verified=True,
            korean_verified=False,
            ui_locale_independent=True,
            paired_reply_replayable=True,
        ),
        evidence=_evidence(),
    )
    score = score_quality_item(measurement, contract=CHATOPS_QUALITY_CONTRACT_V1)

    assert measurement.item_id == 41
    assert dict(measurement.components)[QualityDimension.FUNCTIONAL_CORRECTNESS] == 0.5
    assert score.final_score < 9.8
    assert score.passed is False


def test_persistence_fidelity_applies_missing_frozen_corpus_cap() -> None:
    measurement = measure_persistence_fidelity(
        PersistenceFidelityObservation(
            envelope=_envelope(ContextLocaleScorecardItem.PERSISTENCE),
            conversation_reloaded_exact=True,
            latest_operator_turn_exact=True,
            first_operator_question_exact=True,
            principal_scope_preserved=True,
            restart_recovery_bounded=True,
            replayable_digest_bound=True,
        ),
        evidence=_evidence(frozen_hidden_corpus_present=False),
    )
    score = score_quality_item(measurement, contract=CHATOPS_QUALITY_CONTRACT_V1)

    assert score.applied_caps == (QualityHardCap.NO_FROZEN_BLIND_CORPUS,)
    assert score.final_score == 9.5
    assert score.passed is False


def test_context_isolation_triggers_critical_escape_on_hidden_scope_leak() -> None:
    measurement = measure_context_isolation(
        ContextIsolationObservation(
            envelope=_envelope(ContextLocaleScorecardItem.CONTEXT_ISOLATION),
            principal_scope_isolated=True,
            screen_scope_isolated=True,
            agent_scope_isolated=True,
            scoped_correlation_only=True,
            replayable_scope_digest=True,
            hidden_scope_leak_count=1,
        ),
        evidence=_evidence(),
    )
    score = score_quality_item(measurement, contract=CHATOPS_QUALITY_CONTRACT_V1)

    assert score.applied_caps == (QualityHardCap.CRITICAL_SAFETY_ESCAPE,)
    assert score.final_score == 8.0
    assert score.passed is False


def test_screen_awareness_triggers_critical_escape_on_unsupported_claims() -> None:
    measurement = measure_screen_awareness(
        ScreenAwarenessObservation(
            envelope=_envelope(ContextLocaleScorecardItem.SCREEN_AWARENESS),
            route_bound_requires_screen_evidence=True,
            greeting_skips_screen_evidence=True,
            screen_path_fallback_present=True,
            authority_label_distinct=True,
            screen_claims_supported=True,
            replayable_context_digest=True,
            unsupported_screen_claim_count=1,
        ),
        evidence=_evidence(),
    )
    score = score_quality_item(measurement, contract=CHATOPS_QUALITY_CONTRACT_V1)

    assert score.applied_caps == (QualityHardCap.CRITICAL_SAFETY_ESCAPE,)
    assert score.final_score == 8.0
    assert score.passed is False


def test_observation_envelope_is_content_addressed_and_rejects_duplicate_refs() -> None:
    envelope = _envelope(ContextLocaleScorecardItem.PERSONALIZATION)

    assert envelope.observation_id.startswith("scorecard-observation:")

    with pytest.raises(ValueError, match="unique and ordered"):
        ScorecardObservationEnvelope(
            item=ContextLocaleScorecardItem.PERSONALIZATION,
            case_id="personalization:case",
            principal_scope="scope:principal-a",
            source_revision=SOURCE_REVISION,
            provenance_refs=("proof:one", "proof:one"),
            correlation_refs=("corr:one",),
        )
