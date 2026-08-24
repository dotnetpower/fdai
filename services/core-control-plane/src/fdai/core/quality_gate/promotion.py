"""Immutable rubric evidence and fail-closed per-ActionType mode resolution."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from fdai.shared.contracts.models import Mode

_GIT_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_MODEL_BINDING = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_MAX_OBSERVATIONS = 10_000


@dataclass(frozen=True, slots=True)
class RubricCaseObservation:
    """Paired baseline and treatment results for one labeled scenario case."""

    case_id: str
    observed_at: datetime
    expected_hallucination: bool
    baseline_flagged: bool
    treatment_flagged: bool
    baseline_policy_escape: bool
    treatment_policy_escape: bool
    baseline_latency_ms: float
    treatment_latency_ms: float
    baseline_tokens: int
    treatment_tokens: int

    def __post_init__(self) -> None:
        if _IDENTIFIER.fullmatch(self.case_id) is None:
            raise ValueError("rubric promotion case_id MUST be a canonical identifier")
        if self.observed_at.tzinfo is None:
            raise ValueError("rubric promotion observed_at MUST be timezone-aware")
        flags = (
            self.expected_hallucination,
            self.baseline_flagged,
            self.treatment_flagged,
            self.baseline_policy_escape,
            self.treatment_policy_escape,
        )
        if any(not isinstance(flag, bool) for flag in flags):
            raise ValueError("rubric promotion labels and outcomes MUST be boolean")
        latencies = (self.baseline_latency_ms, self.treatment_latency_ms)
        if any(not math.isfinite(value) or value < 0.0 for value in latencies):
            raise ValueError("rubric promotion latency MUST be finite and non-negative")
        tokens = (self.baseline_tokens, self.treatment_tokens)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in tokens
        ):
            raise ValueError("rubric promotion token counts MUST be non-negative integers")


@dataclass(frozen=True, slots=True)
class RubricPromotionBatch:
    """One sealed ActionType evaluation over an exact revision and scenario set."""

    fdai_revision: str
    scenario_set_version: str
    action_type_name: str
    action_type_version: str
    action_type_digest: str
    prompt_revision_digest: str
    threshold_config_digest: str
    primary_model_id: str
    judge_model_id: str
    sealed_at: datetime
    observations: tuple[RubricCaseObservation, ...]

    def __post_init__(self) -> None:
        if _GIT_REVISION.fullmatch(self.fdai_revision) is None:
            raise ValueError("rubric promotion FDAI revision MUST be immutable")
        for name, value in (
            ("scenario_set_version", self.scenario_set_version),
            ("action_type_name", self.action_type_name),
        ):
            if _IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"rubric promotion {name} MUST be a canonical identifier")
        for name, value in (
            ("prompt_revision_digest", self.prompt_revision_digest),
            ("threshold_config_digest", self.threshold_config_digest),
            ("action_type_digest", self.action_type_digest),
        ):
            if not _is_digest(value):
                raise ValueError(f"rubric promotion {name} MUST be SHA-256")
        for name, value in (
            ("primary_model_id", self.primary_model_id),
            ("judge_model_id", self.judge_model_id),
        ):
            if _MODEL_BINDING.fullmatch(value) is None:
                raise ValueError(f"rubric promotion {name} is invalid")
        if self.primary_model_id == self.judge_model_id:
            raise ValueError("rubric promotion judge MUST be independent from the primary model")
        if not self.action_type_version or len(self.action_type_version) > 128:
            raise ValueError("rubric promotion ActionType version MUST be bounded")
        if self.sealed_at.tzinfo is None:
            raise ValueError("rubric promotion sealed_at MUST be timezone-aware")
        if not self.observations:
            raise ValueError("rubric promotion batch MUST contain observations")
        if len(self.observations) > _MAX_OBSERVATIONS:
            raise ValueError("rubric promotion observations exceed their limit")
        if len({item.case_id for item in self.observations}) != len(self.observations):
            raise ValueError("rubric promotion case ids MUST be unique")
        if any(item.observed_at > self.sealed_at for item in self.observations):
            raise ValueError("rubric promotion observations MUST NOT follow sealing")

    @property
    def content_digest(self) -> str:
        material = {
            "action_type_digest": self.action_type_digest,
            "action_type_name": self.action_type_name,
            "action_type_version": self.action_type_version,
            "fdai_revision": self.fdai_revision,
            "judge_model_id": self.judge_model_id,
            "observations": [
                {
                    "baseline_flagged": item.baseline_flagged,
                    "baseline_latency_ms": item.baseline_latency_ms,
                    "baseline_policy_escape": item.baseline_policy_escape,
                    "baseline_tokens": item.baseline_tokens,
                    "case_id": item.case_id,
                    "expected_hallucination": item.expected_hallucination,
                    "observed_at": item.observed_at.astimezone(UTC).isoformat(),
                    "treatment_flagged": item.treatment_flagged,
                    "treatment_latency_ms": item.treatment_latency_ms,
                    "treatment_policy_escape": item.treatment_policy_escape,
                    "treatment_tokens": item.treatment_tokens,
                }
                for item in sorted(self.observations, key=lambda value: value.case_id)
            ],
            "primary_model_id": self.primary_model_id,
            "prompt_revision_digest": self.prompt_revision_digest,
            "scenario_set_version": self.scenario_set_version,
            "sealed_at": self.sealed_at.astimezone(UTC).isoformat(),
            "threshold_config_digest": self.threshold_config_digest,
        }
        return _digest(material)


@dataclass(frozen=True, slots=True)
class RubricIndependentReview:
    """Independent approval or rejection of one exact sealed rubric batch."""

    review_id: str
    evidence_digest: str
    reviewed_at: datetime
    approved: bool

    def __post_init__(self) -> None:
        if _IDENTIFIER.fullmatch(self.review_id) is None:
            raise ValueError("rubric promotion review_id MUST be a canonical identifier")
        if not _is_digest(self.evidence_digest):
            raise ValueError("rubric promotion review evidence MUST be SHA-256")
        if self.reviewed_at.tzinfo is None:
            raise ValueError("rubric promotion reviewed_at MUST be timezone-aware")
        if not isinstance(self.approved, bool):
            raise ValueError("rubric promotion review approval MUST be boolean")

    @property
    def content_digest(self) -> str:
        return _digest(
            {
                "approved": self.approved,
                "evidence_digest": self.evidence_digest,
                "review_id": self.review_id,
                "reviewed_at": self.reviewed_at.astimezone(UTC).isoformat(),
            }
        )


@dataclass(frozen=True, slots=True)
class RubricPromotionPolicy:
    """Quality, cost, freshness, and safety bounds for rubric enforcement.

    Catch-rate minimums apply to the 95% Wilson lower bound, while
    false-positive ceilings apply to its upper bound.
    """

    min_samples: int
    min_hallucination_cases: int
    min_clean_cases: int
    min_treatment_catch_rate: float
    min_catch_rate_gain: float
    max_treatment_false_positive_rate: float
    max_false_positive_rate_increase: float
    max_added_latency_ms: float
    max_added_tokens: float
    max_evidence_age_days: int
    max_policy_escapes: int = 0

    def __post_init__(self) -> None:
        counts = (self.min_samples, self.min_hallucination_cases, self.min_clean_cases)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in counts
        ):
            raise ValueError("rubric promotion sample minimums MUST be positive integers")
        if self.max_policy_escapes < 0:
            raise ValueError("rubric promotion policy escapes MUST be non-negative")
        if (
            not isinstance(self.max_evidence_age_days, int)
            or isinstance(self.max_evidence_age_days, bool)
            or self.max_evidence_age_days < 1
        ):
            raise ValueError("rubric promotion evidence age MUST be a positive integer")
        rates = (
            self.min_treatment_catch_rate,
            self.min_catch_rate_gain,
            self.max_treatment_false_positive_rate,
            self.max_false_positive_rate_increase,
        )
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in rates):
            raise ValueError("rubric promotion rates MUST be in [0, 1]")
        costs = (self.max_added_latency_ms, self.max_added_tokens)
        if any(not math.isfinite(value) or value < 0.0 for value in costs):
            raise ValueError("rubric promotion cost ceilings MUST be finite and non-negative")


@dataclass(frozen=True, slots=True)
class RubricPromotionReceipt:
    """Evidence-bound result of evaluating one rubric promotion batch."""

    fdai_revision: str
    scenario_set_version: str
    action_type_name: str
    action_type_version: str
    action_type_digest: str
    evidence_digest: str
    review_digest: str
    sealed_at: datetime
    reviewed_at: datetime
    expires_at: datetime
    sample_count: int
    hallucination_cases: int
    clean_cases: int
    baseline_catch_rate: float
    baseline_catch_ci: tuple[float, float]
    treatment_catch_rate: float
    treatment_catch_ci: tuple[float, float]
    baseline_false_positive_rate: float
    baseline_false_positive_ci: tuple[float, float]
    treatment_false_positive_rate: float
    treatment_false_positive_ci: tuple[float, float]
    catch_rate_gain: float
    false_positive_rate_increase: float
    average_added_latency_ms: float
    average_added_tokens: float
    treatment_policy_escapes: int
    ready: bool
    gaps: tuple[str, ...]

    def __post_init__(self) -> None:
        if _GIT_REVISION.fullmatch(self.fdai_revision) is None:
            raise ValueError("rubric receipt FDAI revision MUST be immutable")
        for name, value in (
            ("scenario_set_version", self.scenario_set_version),
            ("action_type_name", self.action_type_name),
        ):
            if _IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"rubric receipt {name} MUST be a canonical identifier")
        if (
            not _is_digest(self.action_type_digest)
            or not _is_digest(self.evidence_digest)
            or not _is_digest(self.review_digest)
        ):
            raise ValueError("rubric receipt evidence and review references MUST be SHA-256")
        if not self.action_type_version or len(self.action_type_version) > 128:
            raise ValueError("rubric receipt ActionType version MUST be bounded")
        timestamps = (self.sealed_at, self.reviewed_at, self.expires_at)
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError("rubric receipt timestamps MUST be timezone-aware")
        if not self.sealed_at <= self.reviewed_at < self.expires_at:
            raise ValueError("rubric receipt timestamps MUST be ordered")
        counts = (self.sample_count, self.hallucination_cases, self.clean_cases)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts
        ):
            raise ValueError("rubric receipt sample counts MUST be non-negative integers")
        if (
            self.sample_count < 1
            or self.hallucination_cases + self.clean_cases != self.sample_count
        ):
            raise ValueError("rubric receipt cohorts MUST partition a non-empty sample")
        rates = (
            self.baseline_catch_rate,
            self.treatment_catch_rate,
            self.baseline_false_positive_rate,
            self.treatment_false_positive_rate,
        )
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in rates):
            raise ValueError("rubric receipt rates MUST be in [0, 1]")
        intervals = (
            self.baseline_catch_ci,
            self.treatment_catch_ci,
            self.baseline_false_positive_ci,
            self.treatment_false_positive_ci,
        )
        if any(not _valid_interval(value) for value in intervals):
            raise ValueError("rubric receipt confidence intervals MUST be ordered in [0, 1]")
        deltas = (
            self.catch_rate_gain,
            self.false_positive_rate_increase,
            self.average_added_latency_ms,
            self.average_added_tokens,
        )
        if any(not math.isfinite(value) for value in deltas):
            raise ValueError("rubric receipt deltas MUST be finite")
        if (
            not isinstance(self.treatment_policy_escapes, int)
            or isinstance(self.treatment_policy_escapes, bool)
            or self.treatment_policy_escapes < 0
        ):
            raise ValueError("rubric receipt policy escapes MUST be a non-negative integer")
        if len(set(self.gaps)) != len(self.gaps) or any(
            not gap or len(gap) > 256 for gap in self.gaps
        ):
            raise ValueError("rubric receipt gaps MUST be unique bounded values")
        if self.ready != (not self.gaps):
            raise ValueError("rubric receipt ready MUST equal absence of gaps")

    def as_json(self) -> dict[str, object]:
        return {
            "action_type_digest": self.action_type_digest,
            "action_type_name": self.action_type_name,
            "action_type_version": self.action_type_version,
            "average_added_latency_ms": self.average_added_latency_ms,
            "average_added_tokens": self.average_added_tokens,
            "baseline_catch_ci": list(self.baseline_catch_ci),
            "baseline_catch_rate": self.baseline_catch_rate,
            "baseline_false_positive_ci": list(self.baseline_false_positive_ci),
            "baseline_false_positive_rate": self.baseline_false_positive_rate,
            "catch_rate_gain": self.catch_rate_gain,
            "clean_cases": self.clean_cases,
            "evidence_digest": self.evidence_digest,
            "false_positive_rate_increase": self.false_positive_rate_increase,
            "fdai_revision": self.fdai_revision,
            "gaps": list(self.gaps),
            "hallucination_cases": self.hallucination_cases,
            "ready": self.ready,
            "review_digest": self.review_digest,
            "reviewed_at": self.reviewed_at.astimezone(UTC).isoformat(),
            "sample_count": self.sample_count,
            "scenario_set_version": self.scenario_set_version,
            "sealed_at": self.sealed_at.astimezone(UTC).isoformat(),
            "treatment_catch_ci": list(self.treatment_catch_ci),
            "treatment_catch_rate": self.treatment_catch_rate,
            "treatment_false_positive_ci": list(self.treatment_false_positive_ci),
            "treatment_false_positive_rate": self.treatment_false_positive_rate,
            "treatment_policy_escapes": self.treatment_policy_escapes,
            "expires_at": self.expires_at.astimezone(UTC).isoformat(),
        }

    @property
    def content_digest(self) -> str:
        return _digest(self.as_json())


class RubricPromotionEvaluator:
    """Reduce exact paired observations to a non-authoritative promotion receipt."""

    def __init__(
        self,
        *,
        expected_fdai_revision: str,
        expected_scenario_set_version: str,
        policy: RubricPromotionPolicy,
        as_of_fn: object = None,
    ) -> None:
        if _GIT_REVISION.fullmatch(expected_fdai_revision) is None:
            raise ValueError("expected FDAI revision MUST be immutable")
        if _IDENTIFIER.fullmatch(expected_scenario_set_version) is None:
            raise ValueError("expected scenario set version MUST be canonical")
        self._fdai_revision = expected_fdai_revision
        self._scenario_set_version = expected_scenario_set_version
        self._policy = policy
        self._as_of_fn = as_of_fn

    def evaluate(
        self,
        batch: RubricPromotionBatch,
        review: RubricIndependentReview,
    ) -> RubricPromotionReceipt:
        observations = batch.observations
        hallucinations = tuple(item for item in observations if item.expected_hallucination)
        clean = tuple(item for item in observations if not item.expected_hallucination)
        baseline_caught = sum(item.baseline_flagged for item in hallucinations)
        treatment_caught = sum(item.treatment_flagged for item in hallucinations)
        baseline_false_positives = sum(item.baseline_flagged for item in clean)
        treatment_false_positives = sum(item.treatment_flagged for item in clean)
        baseline_catch_rate = _rate(baseline_caught, len(hallucinations))
        treatment_catch_rate = _rate(treatment_caught, len(hallucinations))
        baseline_false_positive_rate = _rate(baseline_false_positives, len(clean))
        treatment_false_positive_rate = _rate(treatment_false_positives, len(clean))
        added_latency = sum(
            item.treatment_latency_ms - item.baseline_latency_ms for item in observations
        ) / len(observations)
        added_tokens = sum(
            item.treatment_tokens - item.baseline_tokens for item in observations
        ) / len(observations)
        treatment_policy_escapes = sum(item.treatment_policy_escape for item in observations)
        catch_gain = treatment_catch_rate - baseline_catch_rate
        false_positive_increase = treatment_false_positive_rate - baseline_false_positive_rate
        treatment_catch_ci = _wilson_interval(treatment_caught, len(hallucinations))
        treatment_false_positive_ci = _wilson_interval(treatment_false_positives, len(clean))
        as_of = self._as_of()
        expires_at = review.reviewed_at + timedelta(days=self._policy.max_evidence_age_days)

        gaps: list[str] = []
        if batch.fdai_revision != self._fdai_revision:
            gaps.append("fdai_revision_mismatch")
        if batch.scenario_set_version != self._scenario_set_version:
            gaps.append("scenario_set_version_mismatch")
        if review.evidence_digest != batch.content_digest:
            gaps.append("review_evidence_mismatch")
        if review.reviewed_at < batch.sealed_at:
            gaps.append("review_precedes_sealing")
        if batch.sealed_at > as_of:
            gaps.append("batch_sealed_in_future")
        if review.reviewed_at > as_of:
            gaps.append("reviewed_in_future")
        if expires_at <= as_of:
            gaps.append("rubric_evidence_expired")
        if not review.approved:
            gaps.append("independent_review_rejected")
        if len(observations) < self._policy.min_samples:
            gaps.append(f"sample_count={len(observations)}<min_samples={self._policy.min_samples}")
        if len(hallucinations) < self._policy.min_hallucination_cases:
            gaps.append(
                f"hallucination_cases={len(hallucinations)}"
                f"<min_hallucination_cases={self._policy.min_hallucination_cases}"
            )
        if len(clean) < self._policy.min_clean_cases:
            gaps.append(f"clean_cases={len(clean)}<min_clean_cases={self._policy.min_clean_cases}")
        if treatment_catch_ci[0] < self._policy.min_treatment_catch_rate:
            gaps.append("treatment_catch_ci_below_minimum")
        if catch_gain < self._policy.min_catch_rate_gain:
            gaps.append("catch_rate_gain_below_minimum")
        if treatment_false_positive_ci[1] > self._policy.max_treatment_false_positive_rate:
            gaps.append("treatment_false_positive_ci_above_maximum")
        if false_positive_increase > self._policy.max_false_positive_rate_increase:
            gaps.append("false_positive_rate_increase_above_maximum")
        if added_latency > self._policy.max_added_latency_ms:
            gaps.append("added_latency_above_maximum")
        if added_tokens > self._policy.max_added_tokens:
            gaps.append("added_tokens_above_maximum")
        if treatment_policy_escapes > self._policy.max_policy_escapes:
            gaps.append("treatment_policy_escapes_above_maximum")

        return RubricPromotionReceipt(
            fdai_revision=batch.fdai_revision,
            scenario_set_version=batch.scenario_set_version,
            action_type_name=batch.action_type_name,
            action_type_version=batch.action_type_version,
            action_type_digest=batch.action_type_digest,
            evidence_digest=batch.content_digest,
            review_digest=review.content_digest,
            sealed_at=batch.sealed_at,
            reviewed_at=review.reviewed_at,
            expires_at=expires_at,
            sample_count=len(observations),
            hallucination_cases=len(hallucinations),
            clean_cases=len(clean),
            baseline_catch_rate=round(baseline_catch_rate, 4),
            baseline_catch_ci=_rounded_interval(
                _wilson_interval(baseline_caught, len(hallucinations))
            ),
            treatment_catch_rate=round(treatment_catch_rate, 4),
            treatment_catch_ci=_rounded_interval(treatment_catch_ci),
            baseline_false_positive_rate=round(baseline_false_positive_rate, 4),
            baseline_false_positive_ci=_rounded_interval(
                _wilson_interval(baseline_false_positives, len(clean))
            ),
            treatment_false_positive_rate=round(treatment_false_positive_rate, 4),
            treatment_false_positive_ci=_rounded_interval(treatment_false_positive_ci),
            catch_rate_gain=round(catch_gain, 4),
            false_positive_rate_increase=round(false_positive_increase, 4),
            average_added_latency_ms=round(added_latency, 3),
            average_added_tokens=round(added_tokens, 3),
            treatment_policy_escapes=treatment_policy_escapes,
            ready=not gaps,
            gaps=tuple(gaps),
        )

    def _as_of(self) -> datetime:
        if self._as_of_fn is None:
            return datetime.now(tz=UTC)
        value = self._as_of_fn()  # type: ignore[operator]
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise TypeError("rubric promotion as_of_fn MUST return aware datetime")
        return value


class ActionModeRecordView(Protocol):
    fdai_revision: str | None
    scenario_set_version: str | None
    action_type_version: str | None
    action_type_digest: str | None


@runtime_checkable
class ActionModeSource(Protocol):
    def mode_of(self, action_type: str) -> Mode: ...

    def record(self, action_type: str) -> ActionModeRecordView | None: ...


@runtime_checkable
class RubricPromotionReceiptVerifier(Protocol):
    def verify(self, receipt: RubricPromotionReceipt) -> bool: ...


@runtime_checkable
class RubricPromotionReceiptSource(Protocol):
    def current(self, action_type_name: str) -> RubricPromotionReceipt | None: ...


@dataclass(frozen=True, slots=True)
class RubricModeDecision:
    mode: Mode
    reason: str
    evidence_digest: str | None = None


@runtime_checkable
class RubricModeResolver(Protocol):
    def resolve(self, action_type_name: str) -> RubricModeDecision: ...


class RubricPromotionRegistry(RubricModeResolver):
    """Resolve rubric mode without ever raising the ActionType's authority."""

    def __init__(
        self,
        *,
        action_modes: ActionModeSource,
        receipt_verifier: RubricPromotionReceiptVerifier,
        receipt_source: RubricPromotionReceiptSource | None = None,
        allow_in_memory: bool = False,
        now_fn: object = None,
    ) -> None:
        if receipt_source is None and not allow_in_memory:
            raise ValueError("rubric promotion receipt source is required outside tests")
        self._action_modes = action_modes
        self._receipt_verifier = receipt_verifier
        self._receipt_source = receipt_source
        self._now_fn = now_fn
        self._receipts: dict[str, RubricPromotionReceipt] = {}

    def consider(self, receipt: RubricPromotionReceipt) -> RubricModeDecision:
        self._receipts[receipt.action_type_name] = receipt
        return self.resolve(receipt.action_type_name)

    def resolve(self, action_type_name: str) -> RubricModeDecision:
        try:
            action_mode = self._action_modes.mode_of(action_type_name)
            action_record = self._action_modes.record(action_type_name)
        except Exception as exc:  # noqa: BLE001 - authority resolution fails closed
            return RubricModeDecision(
                Mode.SHADOW,
                f"action_mode_source_error:{type(exc).__name__}",
            )
        if action_mode is not Mode.ENFORCE:
            return RubricModeDecision(Mode.SHADOW, "action_type_not_enforce")
        if action_record is None:
            return RubricModeDecision(Mode.SHADOW, "action_type_authority_missing")
        try:
            receipt = (
                self._receipt_source.current(action_type_name)
                if self._receipt_source is not None
                else self._receipts.get(action_type_name)
            )
        except Exception as exc:  # noqa: BLE001 - authority resolution fails closed
            return RubricModeDecision(
                Mode.SHADOW,
                f"rubric_receipt_source_error:{type(exc).__name__}",
            )
        if receipt is None:
            return RubricModeDecision(Mode.SHADOW, "rubric_receipt_missing")
        if not receipt.ready:
            return RubricModeDecision(
                Mode.SHADOW,
                "rubric_receipt_not_ready",
                receipt.evidence_digest,
            )
        if receipt.expires_at <= self._now():
            return RubricModeDecision(
                Mode.SHADOW,
                "rubric_receipt_expired",
                receipt.evidence_digest,
            )
        try:
            authority_identity = (
                action_record.fdai_revision,
                action_record.scenario_set_version,
                action_record.action_type_version,
                action_record.action_type_digest,
            )
        except Exception as exc:  # noqa: BLE001 - malformed authority fails closed
            return RubricModeDecision(
                Mode.SHADOW,
                f"rubric_receipt_authority_invalid:{type(exc).__name__}",
                receipt.evidence_digest,
            )
        receipt_identity = (
            receipt.fdai_revision,
            receipt.scenario_set_version,
            receipt.action_type_version,
            receipt.action_type_digest,
        )
        if authority_identity != receipt_identity:
            return RubricModeDecision(
                Mode.SHADOW,
                "rubric_receipt_authority_mismatch",
                receipt.evidence_digest,
            )
        try:
            verified = self._receipt_verifier.verify(receipt)
        except Exception as exc:  # noqa: BLE001 - authority resolution fails closed
            return RubricModeDecision(
                Mode.SHADOW,
                f"rubric_receipt_verifier_error:{type(exc).__name__}",
                receipt.evidence_digest,
            )
        if not verified:
            return RubricModeDecision(
                Mode.SHADOW,
                "rubric_receipt_rejected",
                receipt.evidence_digest,
            )
        return RubricModeDecision(Mode.ENFORCE, "rubric_receipt_ready", receipt.evidence_digest)

    def _now(self) -> datetime:
        if self._now_fn is None:
            return datetime.now(tz=UTC)
        value = self._now_fn()  # type: ignore[operator]
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise TypeError("rubric promotion now_fn MUST return aware datetime")
        return value


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _digest(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _rate(successes: int, samples: int) -> float:
    return successes / samples if samples else 0.0


def _rounded_interval(interval: tuple[float, float]) -> tuple[float, float]:
    return round(interval[0], 4), round(interval[1], 4)


def _valid_interval(value: tuple[float, float]) -> bool:
    return (
        len(value) == 2
        and all(math.isfinite(item) and 0.0 <= item <= 1.0 for item in value)
        and value[0] <= value[1]
    )


def _wilson_interval(successes: int, samples: int) -> tuple[float, float]:
    if samples == 0:
        return 0.0, 1.0
    z = 1.959963984540054
    proportion = successes / samples
    denominator = 1.0 + z * z / samples
    center = (proportion + z * z / (2.0 * samples)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1.0 - proportion) / samples + z * z / (4.0 * samples * samples))
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


__all__ = [
    "ActionModeSource",
    "ActionModeRecordView",
    "RubricCaseObservation",
    "RubricIndependentReview",
    "RubricModeDecision",
    "RubricModeResolver",
    "RubricPromotionBatch",
    "RubricPromotionEvaluator",
    "RubricPromotionPolicy",
    "RubricPromotionReceipt",
    "RubricPromotionReceiptSource",
    "RubricPromotionReceiptVerifier",
    "RubricPromotionRegistry",
]
