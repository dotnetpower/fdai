"""T1 pattern-library growth guardrails.

Phase 4 § Pattern Library Growth. The pattern library MUST NOT
self-promote: a new pattern is only ingest-eligible when it was
observed from an **auto-resolved, non-rolled-back, verified** action;
and it MUST clear a **temporal-holdout** validation before it can drive
a T1 action.

The training-set intake filter and the temporal-holdout evaluator are
pure functions of their inputs, so the same fixtures unit-test both.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class IntakeOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED_ROLLED_BACK = "rejected_rolled_back"
    REJECTED_NOT_AUTO = "rejected_not_auto"
    REJECTED_NOT_VERIFIED = "rejected_not_verified"


@dataclass(frozen=True, slots=True)
class OutcomeRecord:
    """One executed-action outcome record from the audit log."""

    action_id: str
    action_type_id: str
    observed_at: datetime
    was_auto: bool
    """True only when the risk-gate returned AUTO (no HIL)."""

    was_verified: bool
    """True only when the executor's verification (dry-run/what-if
    parity + post-condition check) passed."""

    was_rolled_back: bool


@dataclass(frozen=True, slots=True)
class IntakeDecision:
    action_id: str
    outcome: IntakeOutcome


def evaluate_intake(record: OutcomeRecord) -> IntakeDecision:
    """Reject anything that is not auto + verified + not rolled back."""
    if record.was_rolled_back:
        return IntakeDecision(record.action_id, IntakeOutcome.REJECTED_ROLLED_BACK)
    if not record.was_auto:
        return IntakeDecision(record.action_id, IntakeOutcome.REJECTED_NOT_AUTO)
    if not record.was_verified:
        return IntakeDecision(record.action_id, IntakeOutcome.REJECTED_NOT_VERIFIED)
    return IntakeDecision(record.action_id, IntakeOutcome.ACCEPTED)


# ---------------------------------------------------------------------------
# Temporal-holdout validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PatternCandidate:
    """A candidate pattern with the timestamp it was learned at."""

    pattern_id: str
    action_type_id: str
    learned_at: datetime


@dataclass(frozen=True, slots=True)
class PatternValidationSample:
    """One holdout observation of an already-known pattern."""

    pattern_id: str
    observed_at: datetime
    was_correct: bool


class HoldoutOutcome(StrEnum):
    PASS = "pass"  # noqa: S105 - enum value, not a secret
    """FP rate on the holdout was <= ceiling."""

    FAIL_FP_RATE = "fail_fp_rate"
    """FP rate exceeded ceiling → pattern is rejected / demoted."""

    INSUFFICIENT_DATA = "insufficient_data"
    """Not enough holdout samples yet; caller SHOULD keep waiting."""


@dataclass(frozen=True, slots=True)
class HoldoutDecision:
    pattern_id: str
    outcome: HoldoutOutcome
    observed_fp_rate: float
    sample_size: int


@dataclass(frozen=True, slots=True)
class TemporalHoldoutConfig:
    min_samples: int = 20
    fp_rate_ceiling: float = 0.1
    """False-positive rate ceiling on the holdout."""


class TemporalHoldoutValidator:
    """Reject patterns whose post-cutoff FP rate breaches the ceiling."""

    def __init__(self, *, config: TemporalHoldoutConfig | None = None) -> None:
        cfg = config or TemporalHoldoutConfig()
        if cfg.min_samples < 1:
            raise ValueError("min_samples MUST be >= 1")
        if not 0.0 <= cfg.fp_rate_ceiling <= 1.0:
            raise ValueError("fp_rate_ceiling MUST be in [0, 1]")
        self._config = cfg

    def evaluate(
        self,
        *,
        candidate: PatternCandidate,
        holdout: Iterable[PatternValidationSample],
    ) -> HoldoutDecision:
        # Only samples STRICTLY AFTER `learned_at` are holdout samples -
        # samples before that timestamp are training-leakage.
        eligible = [
            sample
            for sample in holdout
            if sample.pattern_id == candidate.pattern_id
            and sample.observed_at > candidate.learned_at
        ]
        sample_size = len(eligible)
        if sample_size < self._config.min_samples:
            return HoldoutDecision(
                pattern_id=candidate.pattern_id,
                outcome=HoldoutOutcome.INSUFFICIENT_DATA,
                observed_fp_rate=0.0,
                sample_size=sample_size,
            )
        fp_count = sum(1 for s in eligible if not s.was_correct)
        fp_rate = fp_count / sample_size
        outcome = (
            HoldoutOutcome.FAIL_FP_RATE
            if fp_rate > self._config.fp_rate_ceiling
            else HoldoutOutcome.PASS
        )
        return HoldoutDecision(
            pattern_id=candidate.pattern_id,
            outcome=outcome,
            observed_fp_rate=fp_rate,
            sample_size=sample_size,
        )


__all__ = [
    "HoldoutDecision",
    "HoldoutOutcome",
    "IntakeDecision",
    "IntakeOutcome",
    "OutcomeRecord",
    "PatternCandidate",
    "PatternValidationSample",
    "TemporalHoldoutConfig",
    "TemporalHoldoutValidator",
    "evaluate_intake",
]
