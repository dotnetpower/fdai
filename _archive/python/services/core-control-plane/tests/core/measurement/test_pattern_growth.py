"""Pattern-growth intake filter + temporal-holdout validator."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.measurement.pattern_growth import (
    HoldoutOutcome,
    IntakeOutcome,
    OutcomeRecord,
    PatternCandidate,
    PatternValidationSample,
    TemporalHoldoutConfig,
    TemporalHoldoutValidator,
    evaluate_intake,
)


def _at(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------


def _record(*, auto: bool = True, verified: bool = True, rolled: bool = False) -> OutcomeRecord:
    return OutcomeRecord(
        action_id="a-1",
        action_type_id="remediate.tag-add",
        observed_at=_at("2026-07-05T00:00:00"),
        was_auto=auto,
        was_verified=verified,
        was_rolled_back=rolled,
    )


def test_intake_accepts_auto_verified_non_rolled_back() -> None:
    assert evaluate_intake(_record()).outcome is IntakeOutcome.ACCEPTED


def test_intake_rejects_rolled_back_even_when_auto_verified() -> None:
    assert evaluate_intake(_record(rolled=True)).outcome is IntakeOutcome.REJECTED_ROLLED_BACK


def test_intake_rejects_hil_action() -> None:
    assert evaluate_intake(_record(auto=False)).outcome is IntakeOutcome.REJECTED_NOT_AUTO


def test_intake_rejects_unverified_action() -> None:
    assert evaluate_intake(_record(verified=False)).outcome is IntakeOutcome.REJECTED_NOT_VERIFIED


# ---------------------------------------------------------------------------
# Temporal holdout
# ---------------------------------------------------------------------------


def test_holdout_config_rejects_zero_min_samples() -> None:
    with pytest.raises(ValueError, match="min_samples"):
        TemporalHoldoutValidator(config=TemporalHoldoutConfig(min_samples=0))


def test_holdout_config_rejects_out_of_range_ceiling() -> None:
    with pytest.raises(ValueError, match="fp_rate_ceiling"):
        TemporalHoldoutValidator(config=TemporalHoldoutConfig(fp_rate_ceiling=1.5))


def _samples(pattern_id: str, results: list[tuple[str, bool]]) -> list[PatternValidationSample]:
    return [
        PatternValidationSample(pattern_id=pattern_id, observed_at=_at(iso), was_correct=ok)
        for iso, ok in results
    ]


def test_holdout_returns_insufficient_data_below_min_samples() -> None:
    validator = TemporalHoldoutValidator(
        config=TemporalHoldoutConfig(min_samples=5, fp_rate_ceiling=0.1)
    )
    candidate = PatternCandidate(
        pattern_id="p-1",
        action_type_id="remediate.tag-add",
        learned_at=_at("2026-07-05T00:00:00"),
    )
    samples = _samples(
        "p-1",
        [
            ("2026-07-06T00:00:00", True),
            ("2026-07-07T00:00:00", True),
        ],
    )
    decision = validator.evaluate(candidate=candidate, holdout=samples)
    assert decision.outcome is HoldoutOutcome.INSUFFICIENT_DATA
    assert decision.sample_size == 2


def test_holdout_filters_pre_cutoff_samples_as_training_leakage() -> None:
    validator = TemporalHoldoutValidator(
        config=TemporalHoldoutConfig(min_samples=2, fp_rate_ceiling=0.1)
    )
    candidate = PatternCandidate(
        pattern_id="p-1",
        action_type_id="remediate.tag-add",
        learned_at=_at("2026-07-05T00:00:00"),
    )
    samples = _samples(
        "p-1",
        [
            # These 3 pre-cutoff samples should be filtered out entirely.
            ("2026-07-04T00:00:00", False),
            ("2026-07-04T00:01:00", False),
            ("2026-07-04T00:02:00", False),
            # Only these two post-cutoff samples count.
            ("2026-07-06T00:00:00", True),
            ("2026-07-07T00:00:00", True),
        ],
    )
    decision = validator.evaluate(candidate=candidate, holdout=samples)
    assert decision.sample_size == 2
    assert decision.observed_fp_rate == 0.0
    assert decision.outcome is HoldoutOutcome.PASS


def test_holdout_ignores_other_pattern_ids() -> None:
    validator = TemporalHoldoutValidator(
        config=TemporalHoldoutConfig(min_samples=1, fp_rate_ceiling=0.1)
    )
    candidate = PatternCandidate(
        pattern_id="p-1",
        action_type_id="remediate.tag-add",
        learned_at=_at("2026-07-05T00:00:00"),
    )
    samples = _samples("p-2", [("2026-07-06T00:00:00", False)])
    decision = validator.evaluate(candidate=candidate, holdout=samples)
    assert decision.outcome is HoldoutOutcome.INSUFFICIENT_DATA


def test_holdout_fails_when_fp_rate_exceeds_ceiling() -> None:
    validator = TemporalHoldoutValidator(
        config=TemporalHoldoutConfig(min_samples=4, fp_rate_ceiling=0.1)
    )
    candidate = PatternCandidate(
        pattern_id="p-1",
        action_type_id="remediate.tag-add",
        learned_at=_at("2026-07-05T00:00:00"),
    )
    samples = _samples(
        "p-1",
        [
            ("2026-07-06T00:00:00", True),
            ("2026-07-07T00:00:00", False),
            ("2026-07-08T00:00:00", False),
            ("2026-07-09T00:00:00", True),
        ],
    )
    decision = validator.evaluate(candidate=candidate, holdout=samples)
    assert decision.outcome is HoldoutOutcome.FAIL_FP_RATE
    assert decision.observed_fp_rate == 0.5
