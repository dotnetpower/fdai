"""Tests for deterministic anti-hallucination runtime guards across FDAI's operating ontology."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.conversation.epistemic_coverage import EpistemicStatus
from fdai.core.mscp_profile import MscpAuthorityCeiling
from fdai.core.ontology_platform.anti_hallucination_guards import (
    adjudicate_cross_authority_observations,
    bind_gateway_as_of_cutoff,
    enforce_plan_operand_and_level_guard,
    evaluate_subtractive_rubric_enforcement,
    reauthorize_cached_or_handle_read,
    resolve_bitemporal_record_window,
    resolve_epistemic_empty_posture,
    verify_causal_competitor_refutation_gate,
    verify_multiformat_distillation_conformance_gate,
)


def test_v_prov_and_v_level_reject_nil_uuid_and_level_confusion() -> None:
    bad_nil = enforce_plan_operand_and_level_guard(
        goal_level="instance",
        function_names=("query.manifest",),
        operands=("00000000-0000-0000-0000-000000000000", "ungrounded-vm"),
        grounded_operands=frozenset({"aks-prod-01"}),
    )
    assert bad_nil.accepted is False
    assert "v_level_instance_goal_uses_schema_function:query.manifest" in bad_nil.violations
    assert any("v_prov_nil_identifier_invented" in v for v in bad_nil.violations)
    assert "v_prov_operand_without_source:ungrounded-vm" in bad_nil.violations

    good = enforce_plan_operand_and_level_guard(
        goal_level="instance",
        function_names=("query.recent_resource_changes",),
        operands=("aks-prod-01",),
        grounded_operands=frozenset({"aks-prod-01"}),
    )
    assert good.accepted is True
    assert good.violations == ()


def test_subtractive_rubric_folding_and_disagreement_preservation() -> None:
    scores = {
        "faithfulness": 0.92,
        "evidence_action_alignment": 0.88,
        "completeness": 0.85,
        "reasoning_coherence": 0.90,
    }
    thresholds = {k: 0.80 for k in scores}
    verdict = evaluate_subtractive_rubric_enforcement(
        aggregate_confidence=0.75,
        criterion_scores=scores,
        thresholds=thresholds,
        proposer_publisher="openai",
        judge_publisher="anthropic",
    )
    assert verdict.decision == "pass"
    # Subtractive-only: rubric min (0.85) cannot raise aggregate_confidence (0.75)
    assert verdict.folded_confidence == pytest.approx(0.75)

    # Disagreement from cross-check is never cleared by rubric pass
    disagree = evaluate_subtractive_rubric_enforcement(
        aggregate_confidence=0.95,
        criterion_scores=scores,
        thresholds=thresholds,
        existing_reasons=("cross_check_below_quorum:1/2",),
    )
    assert disagree.decision == "disagree"
    assert disagree.folded_confidence == pytest.approx(0.85)

    # Same publisher fails closed to abstain
    same_pub = evaluate_subtractive_rubric_enforcement(
        aggregate_confidence=0.95,
        criterion_scores=scores,
        thresholds=thresholds,
        proposer_publisher="openai",
        judge_publisher="OpenAI",
    )
    assert same_pub.decision == "abstain"
    assert same_pub.folded_confidence == 0.0


def test_epistemic_empty_posture_requires_closed_population_proof() -> None:
    assert (
        resolve_epistemic_empty_posture(
            row_count=0,
            source_complete=True,
            truncated=False,
            link_coverage_complete=True,
        )
        is EpistemicStatus.VERIFIED_EMPTY
    )
    assert (
        resolve_epistemic_empty_posture(
            row_count=0,
            source_complete=True,
            truncated=True,
            link_coverage_complete=True,
        )
        is EpistemicStatus.UNKNOWN_INCOMPLETE
    )
    assert (
        resolve_epistemic_empty_posture(
            row_count=0,
            source_complete=False,
            truncated=False,
            link_coverage_complete=True,
        )
        is EpistemicStatus.UNKNOWN_INCOMPLETE
    )


def test_cross_authority_adjudication_withholds_peer_conflict() -> None:
    peer_conflict = adjudicate_cross_authority_observations(
        [
            ("arm-inventory", "provider_observed", "Succeeded"),
            ("k8s-telemetry", "telemetry_observed", "Failed"),
        ]
    )
    assert peer_conflict.status == "contested_withheld"
    assert peer_conflict.withheld is True
    assert peer_conflict.resolved_value is None
    assert peer_conflict.ceiling is MscpAuthorityCeiling.HOLD

    subordinated = adjudicate_cross_authority_observations(
        [
            ("arm-inventory", "provider_observed", "Succeeded"),
            ("doc-extract", "document_distilled", "Degraded"),
        ]
    )
    assert subordinated.status == "subordinated_lower_authority"
    assert subordinated.withheld is False
    assert subordinated.resolved_value == "Succeeded"
    assert subordinated.ceiling is MscpAuthorityCeiling.HOLD


def test_gateway_as_of_and_bitemporal_window() -> None:
    now = datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC)
    stale = bind_gateway_as_of_cutoff(
        requested_as_of=now - timedelta(seconds=120),
        gateway_now=now,
        max_skew_seconds=30,
    )
    assert stale.accepted is False
    assert stale.reason == "as_of_stale"

    fresh = bind_gateway_as_of_cutoff(
        requested_as_of=now - timedelta(seconds=10),
        gateway_now=now,
        max_skew_seconds=30,
    )
    assert fresh.accepted is True

    recs = [
        {
            "id": "r1",
            "effective_from": now - timedelta(hours=5),
            "effective_to": now - timedelta(hours=1),
            "recorded_time": now - timedelta(hours=4),
        },
        {
            "id": "r2",
            "effective_from": now - timedelta(hours=1),
            "effective_to": None,
            "recorded_time": now - timedelta(minutes=30),
        },
    ]
    past = resolve_bitemporal_record_window(
        recs,
        valid_at=now - timedelta(hours=2),
        known_at=now,
    )
    assert [r["id"] for r in past] == ["r1"]


def test_causal_refutation_and_reauth_and_distillation_gates() -> None:
    blocked = verify_causal_competitor_refutation_gate(
        refutation_reads_completed=2,
        competitor_dispositions={"comp-a": "refuted", "comp-b": "unresolved"},
    )
    assert blocked.can_claim_cause is False
    assert blocked.posture == "cause_hypothesis_only"
    assert blocked.unresolved_competitors == ("comp-b",)

    verified = verify_causal_competitor_refutation_gate(
        refutation_reads_completed=2,
        competitor_dispositions={"comp-a": "refuted", "comp-b": "refuted"},
    )
    assert verified.can_claim_cause is True
    assert verified.posture == "verified_cause"

    now = datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC)
    d1 = "sha256:" + "a" * 64
    d2 = "sha256:" + "b" * 64
    ok, err = reauthorize_cached_or_handle_read(
        cached_principal_scope_digest=d1,
        cached_purpose="operations-review",
        cached_source_state_digest=d2,
        current_principal_scope_digest=d1,
        current_purpose="operations-review",
        current_source_state_digest="sha256:" + "c" * 64,
        expires_at=now + timedelta(minutes=5),
        now=now,
    )
    assert ok is False
    assert err == "prior_result_source_state_changed"

    dist_ok, dist_err = verify_multiformat_distillation_conformance_gate(
        covered_partitions=("en_markdown", "en_native_pdf", "en_office", "ko_office", "ko_ocr_pdf"),
        unaccounted_span_count=0,
        distinct_model_families=("gpt", "claude", "gemini"),
        agreeing_families_count=3,
    )
    assert dist_ok is True
    assert dist_err is None


def test_critique_hardening_edge_cases() -> None:
    # R2 & R3: NaN / duplicate criterion in rubric enforcement fails closed to abstain
    nan_verdict = evaluate_subtractive_rubric_enforcement(
        aggregate_confidence=0.90,
        criterion_scores={
            "faithfulness": float("nan"),
            "evidence_action_alignment": 0.9,
            "completeness": 0.9,
            "reasoning_coherence": 0.9,
        },
        thresholds={},
    )
    assert nan_verdict.decision == "abstain"
    assert nan_verdict.folded_confidence == 0.0
    assert "rubric_score_invalid_or_nonfinite" in nan_verdict.reasons

    dup_verdict = evaluate_subtractive_rubric_enforcement(
        aggregate_confidence=0.90,
        criterion_scores=(
            ("faithfulness", 0.9),
            ("faithfulness", 0.4),
            ("evidence_action_alignment", 0.9),
            ("completeness", 0.9),
            ("reasoning_coherence", 0.9),
        ),
        thresholds={},
    )
    assert dup_verdict.decision == "abstain"
    assert "rubric_duplicate_or_unknown_criterion" in dup_verdict.reasons

    # R4: Suffix zero and placeholder operands rejected by V-PROV
    placeholder_verdict = enforce_plan_operand_and_level_guard(
        goal_level="instance",
        function_names=("query.recent_resource_changes",),
        operands=("incident-0000", "<resource_id>", "placeholder"),
        grounded_operands=frozenset({"incident-0000", "<resource_id>", "placeholder"}),
    )
    assert placeholder_verdict.accepted is False
    assert len(placeholder_verdict.violations) == 3

    # R5: Bool or negative row_count rejected
    with pytest.raises(ValueError, match="non-negative integer"):
        resolve_epistemic_empty_posture(
            row_count=True,  # type: ignore[arg-type]
            source_complete=True,
            truncated=False,
            link_coverage_complete=True,
        )

    # R6: Unknown authority class or intra-source contradiction fails closed
    unknown_auth = adjudicate_cross_authority_observations(
        [("src-1", "untrusted_scraped", "Running")]
    )
    assert unknown_auth.withheld is True
    assert unknown_auth.ceiling is MscpAuthorityCeiling.HOLD

    intra_conflict = adjudicate_cross_authority_observations(
        [
            ("arm-1", "provider_observed", "Running"),
            ("arm-1", "provider_observed", "Stopped"),
        ]
    )
    assert intra_conflict.withheld is True
    assert intra_conflict.conflicting_sources == ("arm-1",)

    # R7 & R9: Inverted bitemporal interval skipped; unauthorized handle row rejected
    now = datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC)
    inverted = [
        {
            "id": "bad",
            "effective_from": now - timedelta(hours=1),
            "effective_to": now - timedelta(hours=3),
            "recorded_time": now - timedelta(hours=2),
        }
    ]
    assert (
        resolve_bitemporal_record_window(inverted, valid_at=now - timedelta(hours=2), known_at=now)
        == ()
    )

    d1 = "sha256:" + "a" * 64
    ok_row, err_row = reauthorize_cached_or_handle_read(
        cached_principal_scope_digest=d1,
        cached_purpose="operations-review",
        cached_source_state_digest=d1,
        current_principal_scope_digest=d1,
        current_purpose="operations-review",
        current_source_state_digest=d1,
        expires_at=now + timedelta(minutes=5),
        now=now,
        requested_row_ids=("row-1", "row-999"),
        handle_row_ids=("row-1", "row-2"),
    )
    assert ok_row is False
    assert err_row == "prior_result_row_not_in_handle"
