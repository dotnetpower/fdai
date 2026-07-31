"""Immutable promotion evidence for operationally learned actions."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from fdai.shared.contracts.models import CausalEvidenceGrade, OntologyActionType

_GIT_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_MAX_RECORDS = 10_000
_MAX_EVIDENCE_REFS = 64
_EVIDENCE_RANK = {
    CausalEvidenceGrade.ASSOCIATION: 0,
    CausalEvidenceGrade.PREDICTIVE_PRECEDENCE: 1,
    CausalEvidenceGrade.QUASI_EXPERIMENTAL: 2,
    CausalEvidenceGrade.INTERVENTIONAL: 3,
}


class PromotionEvidenceCohort(StrEnum):
    FROZEN_BENCHMARK = "frozen_benchmark"
    LIVE_SHADOW = "live_shadow"


@dataclass(frozen=True, slots=True)
class OperationalPromotionRecord:
    sample_id: str
    action_type_name: str
    cohort: PromotionEvidenceCohort
    observed_at: datetime
    correct: bool
    policy_escape: bool
    rolled_back: bool
    recurrence: bool
    causal_evidence_grade: CausalEvidenceGrade | None
    simulation_requires_review: bool
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("sample_id", self.sample_id),
            ("action_type_name", self.action_type_name),
        ):
            if _IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"operational promotion {name} MUST be a canonical identifier")
        if self.observed_at.tzinfo is None:
            raise ValueError("operational promotion observed_at MUST be timezone-aware")
        if not isinstance(self.cohort, PromotionEvidenceCohort):
            raise ValueError("operational promotion cohort is invalid")
        if self.causal_evidence_grade is not None and not isinstance(
            self.causal_evidence_grade, CausalEvidenceGrade
        ):
            raise ValueError("operational promotion causal evidence grade is invalid")
        checks = (
            self.correct,
            self.policy_escape,
            self.rolled_back,
            self.recurrence,
            self.simulation_requires_review,
        )
        if any(not isinstance(check, bool) for check in checks):
            raise ValueError("operational promotion checks MUST be boolean")
        if (
            not 1 <= len(self.evidence_refs) <= _MAX_EVIDENCE_REFS
            or len(set(self.evidence_refs)) != len(self.evidence_refs)
            or any(not _is_digest(ref) for ref in self.evidence_refs)
        ):
            raise ValueError("operational promotion evidence refs MUST be unique SHA-256 values")


@dataclass(frozen=True, slots=True)
class OperationalPromotionBatch:
    fdai_revision: str
    scenario_set_version: str
    action_type_name: str
    sealed_at: datetime
    records: tuple[OperationalPromotionRecord, ...]

    def __post_init__(self) -> None:
        if _GIT_REVISION.fullmatch(self.fdai_revision) is None:
            raise ValueError("promotion batch fdai_revision MUST be a full immutable revision")
        for name, value in (
            ("scenario_set_version", self.scenario_set_version),
            ("action_type_name", self.action_type_name),
        ):
            if _IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"promotion batch {name} MUST be a canonical identifier")
        if self.sealed_at.tzinfo is None:
            raise ValueError("promotion batch sealed_at MUST be timezone-aware")
        if len(self.records) > _MAX_RECORDS:
            raise ValueError("promotion batch records exceed their limit")
        if len({record.sample_id for record in self.records}) != len(self.records):
            raise ValueError("promotion batch sample ids MUST be unique")
        if any(record.action_type_name != self.action_type_name for record in self.records):
            raise ValueError("promotion batch records MUST match its ActionType")
        if any(record.observed_at > self.sealed_at for record in self.records):
            raise ValueError("promotion batch records MUST NOT follow sealing")

    @property
    def content_digest(self) -> str:
        material = {
            "action_type_name": self.action_type_name,
            "fdai_revision": self.fdai_revision,
            "scenario_set_version": self.scenario_set_version,
            "sealed_at": self.sealed_at.astimezone(UTC).isoformat(),
            "records": [
                {
                    "action_type_name": record.action_type_name,
                    "causal_evidence_grade": (
                        record.causal_evidence_grade.value
                        if record.causal_evidence_grade is not None
                        else None
                    ),
                    "cohort": record.cohort.value,
                    "correct": record.correct,
                    "evidence_refs": record.evidence_refs,
                    "observed_at": record.observed_at.astimezone(UTC).isoformat(),
                    "policy_escape": record.policy_escape,
                    "recurrence": record.recurrence,
                    "rolled_back": record.rolled_back,
                    "sample_id": record.sample_id,
                    "simulation_requires_review": record.simulation_requires_review,
                }
                for record in sorted(self.records, key=lambda item: item.sample_id)
            ],
        }
        encoded = json.dumps(material, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class OperationalPromotionPolicy:
    min_benchmark_samples: int = 1
    min_live_shadow_samples: int = 1
    max_rollback_rate: float = 0.0
    max_recurrence_rate: float = 0.0
    max_simulation_review_rate: float = 0.0
    max_policy_escapes: int = 0
    min_causal_evidence_grade: CausalEvidenceGrade = CausalEvidenceGrade.QUASI_EXPERIMENTAL

    def __post_init__(self) -> None:
        if self.min_benchmark_samples < 1 or self.min_live_shadow_samples < 1:
            raise ValueError("operational promotion cohort minimums MUST be positive")
        if self.max_policy_escapes < 0:
            raise ValueError("operational promotion policy escapes MUST be non-negative")
        rates = (
            self.max_rollback_rate,
            self.max_recurrence_rate,
            self.max_simulation_review_rate,
        )
        if any(not math.isfinite(rate) or not 0.0 <= rate <= 1.0 for rate in rates):
            raise ValueError("operational promotion rate ceilings MUST be in [0, 1]")
        if not isinstance(self.min_causal_evidence_grade, CausalEvidenceGrade):
            raise ValueError("operational promotion minimum causal evidence grade is invalid")


@dataclass(frozen=True, slots=True)
class OperationalPromotionReceipt:
    fdai_revision: str
    scenario_set_version: str
    action_type_name: str
    evidence_digest: str
    observation_days: float
    sample_count: int
    benchmark_samples: int
    live_shadow_samples: int
    correct_count: int
    accuracy: float
    accuracy_ci_lower: float
    accuracy_ci_upper: float
    policy_escapes: int
    rollback_rate: float
    recurrence_rate: float
    simulation_review_rate: float
    causal_evidence_failures: int
    ready: bool
    gaps: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "fdai_revision": self.fdai_revision,
            "scenario_set_version": self.scenario_set_version,
            "action_type_name": self.action_type_name,
            "evidence_digest": self.evidence_digest,
            "observation_days": self.observation_days,
            "sample_count": self.sample_count,
            "benchmark_samples": self.benchmark_samples,
            "live_shadow_samples": self.live_shadow_samples,
            "correct_count": self.correct_count,
            "accuracy": self.accuracy,
            "accuracy_ci_lower": self.accuracy_ci_lower,
            "accuracy_ci_upper": self.accuracy_ci_upper,
            "policy_escapes": self.policy_escapes,
            "rollback_rate": self.rollback_rate,
            "recurrence_rate": self.recurrence_rate,
            "simulation_review_rate": self.simulation_review_rate,
            "causal_evidence_failures": self.causal_evidence_failures,
            "ready": self.ready,
            "gaps": list(self.gaps),
        }


class OperationalPromotionEvaluator:
    """Evaluate one immutable revision and scenario set without promoting it."""

    def __init__(
        self,
        *,
        expected_fdai_revision: str,
        expected_scenario_set_version: str,
        policy: OperationalPromotionPolicy | None = None,
    ) -> None:
        if _GIT_REVISION.fullmatch(expected_fdai_revision) is None:
            raise ValueError("expected FDAI revision MUST be a full immutable revision")
        if _IDENTIFIER.fullmatch(expected_scenario_set_version) is None:
            raise ValueError("expected scenario set version MUST be canonical")
        self._revision = expected_fdai_revision
        self._scenario = expected_scenario_set_version
        self._policy = policy or OperationalPromotionPolicy()

    def evaluate(
        self,
        action_type: OntologyActionType,
        batch: OperationalPromotionBatch,
    ) -> OperationalPromotionReceipt:
        records = batch.records
        sample_count = len(records)
        benchmark_samples = sum(
            record.cohort is PromotionEvidenceCohort.FROZEN_BENCHMARK for record in records
        )
        live_shadow_samples = sum(
            record.cohort is PromotionEvidenceCohort.LIVE_SHADOW for record in records
        )
        correct_count = sum(record.correct for record in records)
        policy_escapes = sum(record.policy_escape for record in records)
        rollback_count = sum(record.rolled_back for record in records)
        recurrence_count = sum(record.recurrence for record in records)
        simulation_review_count = sum(record.simulation_requires_review for record in records)
        accuracy = correct_count / sample_count if sample_count else 0.0
        accuracy_ci_lower, accuracy_ci_upper = _wilson_interval(
            correct_count,
            sample_count,
        )
        rollback_rate = rollback_count / sample_count if sample_count else 0.0
        recurrence_rate = recurrence_count / sample_count if sample_count else 0.0
        simulation_review_rate = simulation_review_count / sample_count if sample_count else 0.0
        observed = [
            record.observed_at
            for record in records
            if record.cohort is PromotionEvidenceCohort.LIVE_SHADOW
        ]
        observation_days = (
            (max(observed) - min(observed)).total_seconds() / 86400.0 if observed else 0.0
        )
        minimum_rank = _EVIDENCE_RANK[self._policy.min_causal_evidence_grade]
        causal_evidence_failures = sum(
            record.causal_evidence_grade is None
            or _EVIDENCE_RANK[record.causal_evidence_grade] < minimum_rank
            for record in records
        )

        gate = action_type.promotion_gate
        gaps: list[str] = []
        if batch.fdai_revision != self._revision:
            gaps.append("fdai_revision_mismatch")
        if batch.scenario_set_version != self._scenario:
            gaps.append("scenario_set_version_mismatch")
        if batch.action_type_name != action_type.name:
            gaps.append("action_type_mismatch")
        if sample_count < gate.min_samples:
            gaps.append(f"sample_count={sample_count}<min_samples={gate.min_samples}")
        if observation_days < gate.min_shadow_days:
            gaps.append(
                f"observation_days={observation_days:.2f}<min_shadow_days={gate.min_shadow_days}"
            )
        if accuracy < gate.min_accuracy:
            gaps.append(f"accuracy={accuracy:.3f}<min_accuracy={gate.min_accuracy}")
        if accuracy_ci_lower < gate.min_accuracy:
            gaps.append(
                f"accuracy_ci_lower={accuracy_ci_lower:.3f}<min_accuracy={gate.min_accuracy}"
            )
        max_policy_escapes = min(
            gate.max_policy_escapes,
            self._policy.max_policy_escapes,
        )
        if policy_escapes > max_policy_escapes:
            gaps.append(f"policy_escapes={policy_escapes}>max_policy_escapes={max_policy_escapes}")
        if benchmark_samples < self._policy.min_benchmark_samples:
            gaps.append(
                f"benchmark_samples={benchmark_samples}"
                f"<min_benchmark_samples={self._policy.min_benchmark_samples}"
            )
        if live_shadow_samples < self._policy.min_live_shadow_samples:
            gaps.append(
                f"live_shadow_samples={live_shadow_samples}"
                f"<min_live_shadow_samples={self._policy.min_live_shadow_samples}"
            )
        if rollback_rate > self._policy.max_rollback_rate:
            gaps.append(
                f"rollback_rate={rollback_rate:.3f}"
                f">max_rollback_rate={self._policy.max_rollback_rate:.3f}"
            )
        if recurrence_rate > self._policy.max_recurrence_rate:
            gaps.append(
                f"recurrence_rate={recurrence_rate:.3f}"
                f">max_recurrence_rate={self._policy.max_recurrence_rate:.3f}"
            )
        if simulation_review_rate > self._policy.max_simulation_review_rate:
            gaps.append(
                f"simulation_review_rate={simulation_review_rate:.3f}"
                f">max_simulation_review_rate={self._policy.max_simulation_review_rate:.3f}"
            )
        if causal_evidence_failures:
            gaps.append(f"causal_evidence_failures={causal_evidence_failures}")

        return OperationalPromotionReceipt(
            fdai_revision=batch.fdai_revision,
            scenario_set_version=batch.scenario_set_version,
            action_type_name=batch.action_type_name,
            evidence_digest=batch.content_digest,
            observation_days=round(observation_days, 3),
            sample_count=sample_count,
            benchmark_samples=benchmark_samples,
            live_shadow_samples=live_shadow_samples,
            correct_count=correct_count,
            accuracy=round(accuracy, 4),
            accuracy_ci_lower=round(accuracy_ci_lower, 4),
            accuracy_ci_upper=round(accuracy_ci_upper, 4),
            policy_escapes=policy_escapes,
            rollback_rate=round(rollback_rate, 4),
            recurrence_rate=round(recurrence_rate, 4),
            simulation_review_rate=round(simulation_review_rate, 4),
            causal_evidence_failures=causal_evidence_failures,
            ready=not gaps,
            gaps=tuple(gaps),
        )


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _wilson_interval(successes: int, samples: int) -> tuple[float, float]:
    if samples == 0:
        return 0.0, 0.0
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
    "OperationalPromotionBatch",
    "OperationalPromotionEvaluator",
    "OperationalPromotionPolicy",
    "OperationalPromotionReceipt",
    "OperationalPromotionRecord",
    "PromotionEvidenceCohort",
]
