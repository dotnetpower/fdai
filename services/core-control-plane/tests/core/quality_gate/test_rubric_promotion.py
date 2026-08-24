from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fdai.core.quality_gate.promotion import (
    RubricCaseObservation,
    RubricIndependentReview,
    RubricPromotionBatch,
    RubricPromotionEvaluator,
    RubricPromotionPolicy,
    RubricPromotionRegistry,
)
from fdai.shared.contracts.models import Mode

_REVISION = "a" * 40
_DIGEST = "b" * 64
_NOW = datetime(2026, 8, 24, tzinfo=UTC)


def _observation(
    case_id: str,
    *,
    hallucination: bool,
    baseline_flagged: bool,
    treatment_flagged: bool,
    treatment_policy_escape: bool = False,
) -> RubricCaseObservation:
    return RubricCaseObservation(
        case_id=case_id,
        observed_at=_NOW,
        expected_hallucination=hallucination,
        baseline_flagged=baseline_flagged,
        treatment_flagged=treatment_flagged,
        baseline_policy_escape=False,
        treatment_policy_escape=treatment_policy_escape,
        baseline_latency_ms=100.0,
        treatment_latency_ms=125.0,
        baseline_tokens=100,
        treatment_tokens=120,
    )


def _batch() -> RubricPromotionBatch:
    observations = tuple(
        _observation(
            f"hallucination-{index}",
            hallucination=True,
            baseline_flagged=index < 5,
            treatment_flagged=True,
        )
        for index in range(20)
    ) + tuple(
        _observation(
            f"clean-{index}",
            hallucination=False,
            baseline_flagged=index < 2,
            treatment_flagged=False,
        )
        for index in range(20)
    )
    return RubricPromotionBatch(
        fdai_revision=_REVISION,
        scenario_set_version="rubric-v1",
        action_type_name="ops.restart-service",
        action_type_version="1.0.0",
        action_type_digest="d" * 64,
        prompt_revision_digest=_DIGEST,
        threshold_config_digest="c" * 64,
        primary_model_id="primary/model-v1",
        judge_model_id="judge/model-v2",
        sealed_at=_NOW + timedelta(minutes=1),
        observations=observations,
    )


def _review(batch: RubricPromotionBatch, *, approved: bool = True) -> RubricIndependentReview:
    return RubricIndependentReview(
        review_id="review-1",
        evidence_digest=batch.content_digest,
        reviewed_at=batch.sealed_at + timedelta(minutes=1),
        approved=approved,
    )


def _policy() -> RubricPromotionPolicy:
    return RubricPromotionPolicy(
        min_samples=40,
        min_hallucination_cases=20,
        min_clean_cases=20,
        min_treatment_catch_rate=0.8,
        min_catch_rate_gain=0.5,
        max_treatment_false_positive_rate=0.2,
        max_false_positive_rate_increase=0.0,
        max_added_latency_ms=30.0,
        max_added_tokens=25.0,
        max_evidence_age_days=30,
    )


def _receipt():
    batch = _batch()
    evaluator = RubricPromotionEvaluator(
        expected_fdai_revision=_REVISION,
        expected_scenario_set_version="rubric-v1",
        policy=_policy(),
        as_of_fn=lambda: _NOW + timedelta(days=1),
    )
    return evaluator.evaluate(batch, _review(batch))


def test_evaluator_returns_ready_receipt_for_paired_improvement() -> None:
    receipt = _receipt()

    assert receipt.ready is True
    assert receipt.gaps == ()
    assert receipt.baseline_catch_rate == 0.25
    assert receipt.treatment_catch_rate == 1.0
    assert receipt.baseline_false_positive_rate == 0.1
    assert receipt.treatment_false_positive_rate == 0.0
    assert receipt.average_added_latency_ms == 25.0
    assert receipt.average_added_tokens == 20.0
    assert receipt.treatment_policy_escapes == 0


@pytest.mark.parametrize(
    ("mutation", "expected_gap"),
    [
        (
            lambda batch, review: (replace(batch, fdai_revision="d" * 40), review),
            "fdai_revision_mismatch",
        ),
        (
            lambda batch, review: (
                batch,
                replace(review, evidence_digest="e" * 64),
            ),
            "review_evidence_mismatch",
        ),
        (
            lambda batch, review: (batch, replace(review, approved=False)),
            "independent_review_rejected",
        ),
    ],
)
def test_evaluator_rejects_mismatched_or_unapproved_authority(
    mutation,
    expected_gap: str,
) -> None:
    batch = _batch()
    review = _review(batch)
    changed_batch, changed_review = mutation(batch, review)
    evaluator = RubricPromotionEvaluator(
        expected_fdai_revision=_REVISION,
        expected_scenario_set_version="rubric-v1",
        policy=_policy(),
        as_of_fn=lambda: _NOW + timedelta(days=1),
    )

    receipt = evaluator.evaluate(changed_batch, changed_review)

    assert receipt.ready is False
    assert expected_gap in receipt.gaps


def test_evaluator_blocks_policy_escape_and_cost_regressions() -> None:
    batch = _batch()
    observations = list(batch.observations)
    observations[0] = replace(
        observations[0],
        treatment_policy_escape=True,
        treatment_latency_ms=1000.0,
        treatment_tokens=1000,
    )
    changed = replace(batch, observations=tuple(observations))
    evaluator = RubricPromotionEvaluator(
        expected_fdai_revision=_REVISION,
        expected_scenario_set_version="rubric-v1",
        policy=_policy(),
        as_of_fn=lambda: _NOW + timedelta(days=1),
    )

    receipt = evaluator.evaluate(changed, _review(changed))

    assert receipt.ready is False
    assert "added_latency_above_maximum" in receipt.gaps
    assert "added_tokens_above_maximum" in receipt.gaps
    assert "treatment_policy_escapes_above_maximum" in receipt.gaps


def test_batch_rejects_same_primary_and_judge_model() -> None:
    batch = _batch()

    with pytest.raises(ValueError, match="judge MUST be independent"):
        replace(batch, judge_model_id=batch.primary_model_id)


def test_receipt_rejects_forged_ready_state() -> None:
    receipt = _receipt()

    with pytest.raises(ValueError, match="ready MUST equal absence of gaps"):
        replace(receipt, ready=True, gaps=("regression",))


def test_receipt_content_digest_covers_metrics() -> None:
    receipt = _receipt()

    assert replace(receipt, average_added_tokens=21.0).content_digest != receipt.content_digest


class _ActionModes:
    def __init__(self, mode: Mode) -> None:
        self.mode = mode

    def mode_of(self, action_type: str) -> Mode:
        return self.mode

    def record(self, action_type: str):
        receipt = _receipt()
        return SimpleNamespace(
            fdai_revision=receipt.fdai_revision,
            scenario_set_version=receipt.scenario_set_version,
            action_type_version=receipt.action_type_version,
            action_type_digest=receipt.action_type_digest,
        )


class _Verifier:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted

    def verify(self, receipt) -> bool:
        return self.accepted


class _ReceiptSource:
    def __init__(self, receipt) -> None:
        self.receipt = receipt

    def current(self, action_type_name: str):
        return self.receipt


def test_registry_requires_action_authority_and_verified_receipt() -> None:
    action_modes = _ActionModes(Mode.SHADOW)
    registry = RubricPromotionRegistry(
        action_modes=action_modes,
        receipt_verifier=_Verifier(),
        allow_in_memory=True,
        now_fn=lambda: _NOW + timedelta(days=1),
    )

    assert registry.consider(_receipt()).mode is Mode.SHADOW
    assert registry.resolve("ops.restart-service").reason == "action_type_not_enforce"

    action_modes.mode = Mode.ENFORCE
    decision = registry.resolve("ops.restart-service")

    assert decision.mode is Mode.ENFORCE
    assert decision.reason == "rubric_receipt_ready"


def test_registry_demotes_only_rubric_on_regressed_receipt() -> None:
    action_modes = _ActionModes(Mode.ENFORCE)
    registry = RubricPromotionRegistry(
        action_modes=action_modes,
        receipt_verifier=_Verifier(),
        allow_in_memory=True,
        now_fn=lambda: _NOW + timedelta(days=1),
    )
    ready = _receipt()
    assert registry.consider(ready).mode is Mode.ENFORCE

    regressed = replace(ready, ready=False, gaps=("regression",))
    decision = registry.consider(regressed)

    assert decision.mode is Mode.SHADOW
    assert decision.reason == "rubric_receipt_not_ready"
    assert action_modes.mode is Mode.ENFORCE


def test_registry_fails_closed_when_receipt_is_rejected() -> None:
    registry = RubricPromotionRegistry(
        action_modes=_ActionModes(Mode.ENFORCE),
        receipt_verifier=_Verifier(accepted=False),
        allow_in_memory=True,
        now_fn=lambda: _NOW + timedelta(days=1),
    )

    decision = registry.consider(_receipt())

    assert decision.mode is Mode.SHADOW
    assert decision.reason == "rubric_receipt_rejected"


def test_registry_reads_current_receipt_snapshot_for_regression() -> None:
    ready = _receipt()
    source = _ReceiptSource(ready)
    registry = RubricPromotionRegistry(
        action_modes=_ActionModes(Mode.ENFORCE),
        receipt_verifier=_Verifier(),
        receipt_source=source,
        now_fn=lambda: _NOW + timedelta(days=1),
    )
    assert registry.resolve(ready.action_type_name).mode is Mode.ENFORCE

    source.receipt = replace(ready, ready=False, gaps=("regression",))
    decision = registry.resolve(ready.action_type_name)

    assert decision.mode is Mode.SHADOW
    assert decision.reason == "rubric_receipt_not_ready"


def test_registry_rejects_mismatched_action_authority() -> None:
    receipt = _receipt()
    action_modes = _ActionModes(Mode.ENFORCE)
    original_record = action_modes.record
    action_modes.record = lambda action_type: SimpleNamespace(  # type: ignore[method-assign]
        **{
            **vars(original_record(action_type)),
            "action_type_digest": "e" * 64,
        }
    )
    registry = RubricPromotionRegistry(
        action_modes=action_modes,
        receipt_verifier=_Verifier(),
        allow_in_memory=True,
        now_fn=lambda: _NOW + timedelta(days=1),
    )

    decision = registry.consider(receipt)

    assert decision.mode is Mode.SHADOW
    assert decision.reason == "rubric_receipt_authority_mismatch"


def test_registry_demotes_expired_receipt() -> None:
    receipt = _receipt()
    registry = RubricPromotionRegistry(
        action_modes=_ActionModes(Mode.ENFORCE),
        receipt_verifier=_Verifier(),
        allow_in_memory=True,
        now_fn=lambda: receipt.expires_at,
    )

    decision = registry.consider(receipt)

    assert decision.mode is Mode.SHADOW
    assert decision.reason == "rubric_receipt_expired"


def test_registry_fails_closed_on_malformed_action_authority() -> None:
    receipt = _receipt()
    action_modes = _ActionModes(Mode.ENFORCE)
    action_modes.record = lambda action_type: object()  # type: ignore[method-assign]
    registry = RubricPromotionRegistry(
        action_modes=action_modes,
        receipt_verifier=_Verifier(),
        allow_in_memory=True,
        now_fn=lambda: _NOW + timedelta(days=1),
    )

    decision = registry.consider(receipt)

    assert decision.mode is Mode.SHADOW
    assert decision.reason == "rubric_receipt_authority_invalid:AttributeError"
