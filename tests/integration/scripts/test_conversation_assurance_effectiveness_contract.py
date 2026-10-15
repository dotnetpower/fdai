from __future__ import annotations

import stat
from dataclasses import replace
from pathlib import Path

import pytest
from scripts.automation.conversation_assurance_effectiveness_contract import (
    EffectivenessAssessment,
    EffectivenessPolicy,
    PairCustodyReceipt,
    RemediationEvidence,
    compose_assessment,
    read_assessment,
    wilson_lower_bound,
    write_assessment,
)


def _policy() -> EffectivenessPolicy:
    return EffectivenessPolicy(
        schema_version="1.0.0",
        policy_id="conversation-effectiveness-v1",
        cohort_id="cohort-one",
        authoritative_base_ref="main",
        required_locales=("en", "ko"),
        minimum_pairs=20,
        minimum_pairs_per_locale=10,
        minimum_improvement_rate=0.8,
        minimum_pair_ratio_delta=0.1,
        confidence_level=0.95,
        maximum_regressions=0,
        maximum_environment_hold_rate=0.1,
        maximum_latency_ms_per_measured_run=120_000,
        maximum_model_calls_per_measured_run=10.0,
        maximum_cost_usd_per_measured_run=1.0,
    )


def _assessment(**updates: object) -> EffectivenessAssessment:
    assessment = EffectivenessAssessment(
        schema_version="1.0.0",
        run_id="holdout-one",
        case_id="holdout-case",
        question_fingerprint="sha256:" + "9" * 64,
        measurement_revision="1" * 40,
        trace_receipt_digest="sha256:" + "8" * 64,
        locale="en",
        rubric_version="conversation-assurance.v2",
        measurement_profile_digest="sha256:" + "a" * 64,
        evidence_snapshot_digest="sha256:" + "b" * 64,
        total_score=10,
        max_score=10,
        mandatory_gate_passed=True,
        objective_oracle_applicable=True,
        objective_oracle_passed=True,
        hard_zero_count=0,
        technical_verified=True,
        failed_rubrics=(),
        mandatory_gate_failures=(),
        latency_ms=1200,
        model_call_count=3,
        cost_usd=0.02,
    )
    return replace(assessment, **updates)


def test_policy_requires_bilingual_predeclared_thresholds() -> None:
    policy = _policy()

    assert policy.authoritative_base_ref == "main"
    assert policy.content_digest.startswith("sha256:")

    with pytest.raises(ValueError, match="English and Korean"):
        replace(policy, required_locales=("en",))
    with pytest.raises(ValueError, match="named base"):
        replace(policy, authoritative_base_ref="HEAD")
    with pytest.raises(ValueError, match="locale floors"):
        replace(policy, minimum_pairs=10, minimum_pairs_per_locale=6)
    with pytest.raises(ValueError, match="ratio delta"):
        replace(policy, minimum_pair_ratio_delta=0.0)


def test_assessment_requires_every_mandatory_effectiveness_gate() -> None:
    assert _assessment().assurance_passed is True
    assert (
        _assessment(
            total_score=9,
            mandatory_gate_passed=False,
            failed_rubrics=("completeness",),
            mandatory_gate_failures=("completeness",),
        ).assurance_passed
        is False
    )
    with pytest.raises(ValueError, match="failed rubrics are inconsistent"):
        _assessment(
            total_score=8,
            mandatory_gate_passed=False,
            failed_rubrics=("completeness", "completeness"),
            mandatory_gate_failures=("completeness",),
        )
    assert _assessment(hard_zero_count=1).assurance_passed is False
    assert (
        _assessment(
            total_score=9,
            mandatory_gate_passed=False,
            technical_verified=False,
            failed_rubrics=("verification",),
            mandatory_gate_failures=("verification",),
        ).assurance_passed
        is False
    )
    assert (
        _assessment(
            total_score=8,
            mandatory_gate_passed=False,
            failed_rubrics=("appropriateness", "completeness"),
            mandatory_gate_failures=("appropriateness", "completeness"),
        ).assurance_passed
        is False
    )


def test_assessment_round_trips_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "assessment.json"
    assessment = _assessment()

    write_assessment(path, assessment)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert read_assessment(path) == assessment


def test_compose_assessment_joins_answer_gate_and_browser_evidence() -> None:
    assessment = compose_assessment(
        run_id="holdout-one",
        case_id="holdout-case",
        question_fingerprint="sha256:" + "9" * 64,
        measurement_revision="1" * 40,
        locale="ko",
        answer_gate={
            "rubric_version": "conversation-assurance.v2",
            "total_score": 9,
            "max_score": 9,
            "rubrics": [
                {"name": "appropriateness", "score": 1},
                {"name": "completeness", "score": 1},
                {"name": "grounding", "score": 1},
                {"name": "verification", "score": 1},
                {"name": "authority_safety", "score": 1},
                {"name": "visualization", "score": None},
                {"name": "investigation_detail", "score": 1},
                {"name": "execution_detail", "score": 1},
                {"name": "performance", "score": 1},
                {"name": "response_integrity", "score": 1},
            ],
            "mandatory_gate": {
                "passed": True,
                "failures": [],
                "objective_oracle": {
                    "applicable": False,
                    "passed": True,
                },
            },
            "technical_verified": True,
        },
        browser_evidence={
            "measurement_profile_digest": "sha256:" + "a" * 64,
            "evidence_snapshot_digest": "sha256:" + "b" * 64,
            "trace_receipt_digest": "sha256:" + "c" * 64,
            "hard_zero_count": 0,
            "latency_ms": 1000,
            "model_call_count": 3,
            "cost_usd": None,
        },
    )

    assert assessment.locale == "ko"
    assert assessment.assurance_passed is True
    assert assessment.cost_usd is None


def test_remediation_evidence_rejects_unowned_change() -> None:
    with pytest.raises(ValueError, match="cannot admit unrelated"):
        RemediationEvidence(
            schema_version="1.0.0",
            run_id="baseline-one",
            source_revision="1" * 40,
            remediation_revision="2" * 40,
            changed_paths_digest="sha256:" + "a" * 64,
            changed_path_count=1,
            validation_receipt_digest="sha256:" + "b" * 64,
            hardening_digest="sha256:" + "c" * 64,
            owning_paths=("scripts/automation",),
            task_owned_only=False,
        )


def test_pair_custody_rejects_disclosed_or_duplicate_holdout() -> None:
    values = {
        "schema_version": "1.0.0",
        "receipt_id": "pair-one",
        "policy_digest": _policy().content_digest,
        "cohort_id": "cohort-one",
        "comparison_group_id": "pair-one",
        "authoritative_base_ref": "main",
        "declared_revision": "1" * 40,
        "baseline_corpus_digest": "sha256:" + "a" * 64,
        "holdout_corpus_digest": "sha256:" + "b" * 64,
        "custodian_identity_digest": "sha256:" + "c" * 64,
        "locale": "en",
        "suite": "external",
        "expected_primary_agent": "Heimdall",
        "expected_routing_method": "semantic_judgment",
        "t2_expectation": "forbidden",
        "challenge_family": "resource-state",
        "objective_oracle": "none",
        "content_disclosed_to_repair_agent": False,
    }
    receipt = PairCustodyReceipt(**values)
    assert receipt.content_digest.startswith("sha256:")

    with pytest.raises(ValueError, match="disclosed"):
        PairCustodyReceipt(
            **{
                **values,
                "content_disclosed_to_repair_agent": True,
            }
        )
    with pytest.raises(ValueError, match="distinct"):
        PairCustodyReceipt(
            **{
                **values,
                "holdout_corpus_digest": values["baseline_corpus_digest"],
            }
        )


def test_wilson_lower_bound_is_conservative() -> None:
    assert wilson_lower_bound(successes=0, trials=0) is None
    lower = wilson_lower_bound(successes=18, trials=20)
    assert lower is not None
    assert 0.69 < lower < 0.70
