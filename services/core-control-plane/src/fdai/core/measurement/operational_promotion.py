"""Immutable promotion evidence for operationally learned actions."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from fdai.shared.contracts.models import CausalEvidenceGrade, OntologyActionType

_GIT_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_MAX_RECORDS = 10_000
_MAX_EVIDENCE_REFS = 64
_CAUSAL_CLOSURES = frozenset({"confirmed", "refuted", "inconclusive", "unsafe"})
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
class CausalPromotionReceipt:
    hypothesis_id: str
    hypothesis_revision_digest: str
    evidence_grade: CausalEvidenceGrade
    status: str
    closure: str | None = None

    def __post_init__(self) -> None:
        if not self.hypothesis_id or len(self.hypothesis_id) > 512:
            raise ValueError("causal promotion hypothesis id MUST be bounded")
        if not _is_digest(self.hypothesis_revision_digest):
            raise ValueError("causal promotion hypothesis revision MUST be SHA-256")
        if self.status not in {"supported", "closed"}:
            raise ValueError("causal promotion hypothesis MUST be supported or closed")
        if self.status == "supported" and self.closure is not None:
            raise ValueError("supported causal promotion evidence MUST NOT declare closure")
        if self.status == "closed" and self.closure not in _CAUSAL_CLOSURES:
            raise ValueError("closed causal promotion evidence requires a valid closure")
        if self.status == "closed" and self.closure != "confirmed":
            raise ValueError("closed causal promotion evidence closure MUST be confirmed")
        if self.evidence_grade is CausalEvidenceGrade.INTERVENTIONAL and (
            self.status != "closed" or self.closure != "confirmed"
        ):
            raise ValueError("interventional promotion evidence requires confirmed closure")

    @property
    def content_digest(self) -> str:
        return _digest(
            {
                "closure": self.closure,
                "evidence_grade": self.evidence_grade.value,
                "hypothesis_id": self.hypothesis_id,
                "hypothesis_revision_digest": self.hypothesis_revision_digest,
                "status": self.status,
            }
        )


class CausalPromotionReceiptVerifier(Protocol):
    def verify(self, receipt: CausalPromotionReceipt) -> bool: ...


class OperationalPromotionUnitVerifier(Protocol):
    def verify(self, record: OperationalPromotionRecord) -> bool: ...


@dataclass(frozen=True, slots=True)
class OperationalPromotionRecord:
    sample_id: str
    measurement_unit_id: str
    audit_sequence: int
    action_type_name: str
    action_type_version: str
    action_type_digest: str
    fdai_revision: str
    scenario_set_version: str
    scenario_case_id: str
    cohort: PromotionEvidenceCohort
    observed_at: datetime
    correct: bool
    policy_escape: bool
    executed: bool
    rolled_back: bool
    recurrence_window_complete: bool
    recurrence: bool
    causal_receipt: CausalPromotionReceipt
    simulation_requires_review: bool
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("sample_id", self.sample_id),
            ("measurement_unit_id", self.measurement_unit_id),
            ("action_type_name", self.action_type_name),
            ("scenario_set_version", self.scenario_set_version),
            ("scenario_case_id", self.scenario_case_id),
        ):
            if _IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"operational promotion {name} MUST be a canonical identifier")
        if self.observed_at.tzinfo is None:
            raise ValueError("operational promotion observed_at MUST be timezone-aware")
        if not isinstance(self.cohort, PromotionEvidenceCohort):
            raise ValueError("operational promotion cohort is invalid")
        if self.audit_sequence < 1:
            raise ValueError("operational promotion audit_sequence MUST be positive")
        if _GIT_REVISION.fullmatch(self.fdai_revision) is None:
            raise ValueError("operational promotion source revision MUST be immutable")
        if not self.action_type_version or not _is_digest(self.action_type_digest):
            raise ValueError("operational promotion ActionType identity is invalid")
        checks = (
            self.correct,
            self.policy_escape,
            self.executed,
            self.rolled_back,
            self.recurrence_window_complete,
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
        object.__setattr__(self, "evidence_refs", tuple(sorted(self.evidence_refs)))
        if self.rolled_back and not self.executed:
            raise ValueError("operational promotion rollback requires an executed action")
        if self.recurrence and not self.recurrence_window_complete:
            raise ValueError("operational promotion recurrence requires a complete window")
        if self.causal_receipt.content_digest not in self.evidence_refs:
            raise ValueError("operational promotion evidence must cite its causal receipt")


@dataclass(frozen=True, slots=True)
class OperationalPromotionBatch:
    fdai_revision: str
    scenario_set_version: str
    action_type_name: str
    action_type_version: str
    action_type_digest: str
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
        if not self.action_type_version or not _is_digest(self.action_type_digest):
            raise ValueError("promotion batch ActionType identity is invalid")
        if len(
            {(record.measurement_unit_id, record.audit_sequence) for record in self.records}
        ) != len(self.records):
            raise ValueError("promotion batch unit corrections MUST be unique")
        lineage_by_unit: dict[str, tuple[object, ...]] = {}
        unit_by_case: dict[tuple[PromotionEvidenceCohort, str], str] = {}
        unit_by_hypothesis: dict[str, str] = {}
        for record in self.records:
            if (
                record.fdai_revision != self.fdai_revision
                or record.scenario_set_version != self.scenario_set_version
                or record.action_type_version != self.action_type_version
                or record.action_type_digest != self.action_type_digest
            ):
                raise ValueError("promotion batch records do not match the sealed manifest")
            lineage = (
                record.cohort,
                record.scenario_case_id,
                record.observed_at,
                record.causal_receipt.hypothesis_id,
            )
            prior_lineage = lineage_by_unit.setdefault(record.measurement_unit_id, lineage)
            if prior_lineage != lineage:
                raise ValueError("promotion batch corrections MUST preserve observation lineage")
            case_key = (record.cohort, record.scenario_case_id)
            prior_case_unit = unit_by_case.setdefault(case_key, record.measurement_unit_id)
            if prior_case_unit != record.measurement_unit_id:
                raise ValueError("promotion batch scenario cases MUST map to one measurement unit")
            prior_hypothesis_unit = unit_by_hypothesis.setdefault(
                record.causal_receipt.hypothesis_id,
                record.measurement_unit_id,
            )
            if prior_hypothesis_unit != record.measurement_unit_id:
                raise ValueError(
                    "promotion batch causal hypotheses MUST map to one measurement unit"
                )
        if any(record.observed_at > self.sealed_at for record in self.records):
            raise ValueError("promotion batch records MUST NOT follow sealing")

    @property
    def content_digest(self) -> str:
        material = {
            "action_type_name": self.action_type_name,
            "action_type_version": self.action_type_version,
            "action_type_digest": self.action_type_digest,
            "fdai_revision": self.fdai_revision,
            "scenario_set_version": self.scenario_set_version,
            "sealed_at": self.sealed_at.astimezone(UTC).isoformat(),
            "records": [
                {
                    "action_type_name": record.action_type_name,
                    "action_type_version": record.action_type_version,
                    "action_type_digest": record.action_type_digest,
                    "audit_sequence": record.audit_sequence,
                    "causal_receipt_digest": record.causal_receipt.content_digest,
                    "cohort": record.cohort.value,
                    "correct": record.correct,
                    "evidence_refs": record.evidence_refs,
                    "executed": record.executed,
                    "fdai_revision": record.fdai_revision,
                    "measurement_unit_id": record.measurement_unit_id,
                    "observed_at": record.observed_at.astimezone(UTC).isoformat(),
                    "policy_escape": record.policy_escape,
                    "recurrence": record.recurrence,
                    "recurrence_window_complete": record.recurrence_window_complete,
                    "rolled_back": record.rolled_back,
                    "sample_id": record.sample_id,
                    "scenario_case_id": record.scenario_case_id,
                    "scenario_set_version": record.scenario_set_version,
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
    action_type_version: str
    action_type_digest: str
    evidence_digest: str
    observation_days: float
    live_observation_days: int
    sample_count: int
    benchmark_samples: int
    live_shadow_samples: int
    correct_count: int
    accuracy: float
    accuracy_ci_lower: float
    accuracy_ci_upper: float
    benchmark_accuracy: float
    benchmark_accuracy_ci_lower: float
    benchmark_accuracy_ci_upper: float
    live_shadow_accuracy: float
    live_shadow_accuracy_ci_lower: float
    live_shadow_accuracy_ci_upper: float
    policy_escapes: int
    rollback_rate: float
    recurrence_rate: float
    executed_samples: int
    recurrence_complete_samples: int
    recurrence_incomplete_samples: int
    simulation_review_rate: float
    causal_evidence_failures: int
    ready: bool
    gaps: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "fdai_revision": self.fdai_revision,
            "scenario_set_version": self.scenario_set_version,
            "action_type_name": self.action_type_name,
            "action_type_version": self.action_type_version,
            "action_type_digest": self.action_type_digest,
            "evidence_digest": self.evidence_digest,
            "observation_days": self.observation_days,
            "live_observation_days": self.live_observation_days,
            "sample_count": self.sample_count,
            "benchmark_samples": self.benchmark_samples,
            "live_shadow_samples": self.live_shadow_samples,
            "correct_count": self.correct_count,
            "accuracy": self.accuracy,
            "accuracy_ci_lower": self.accuracy_ci_lower,
            "accuracy_ci_upper": self.accuracy_ci_upper,
            "benchmark_accuracy": self.benchmark_accuracy,
            "benchmark_accuracy_ci_lower": self.benchmark_accuracy_ci_lower,
            "benchmark_accuracy_ci_upper": self.benchmark_accuracy_ci_upper,
            "live_shadow_accuracy": self.live_shadow_accuracy,
            "live_shadow_accuracy_ci_lower": self.live_shadow_accuracy_ci_lower,
            "live_shadow_accuracy_ci_upper": self.live_shadow_accuracy_ci_upper,
            "policy_escapes": self.policy_escapes,
            "rollback_rate": self.rollback_rate,
            "recurrence_rate": self.recurrence_rate,
            "executed_samples": self.executed_samples,
            "recurrence_complete_samples": self.recurrence_complete_samples,
            "recurrence_incomplete_samples": self.recurrence_incomplete_samples,
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
        causal_receipt_verifier: CausalPromotionReceiptVerifier,
        unit_verifier: OperationalPromotionUnitVerifier,
        policy: OperationalPromotionPolicy | None = None,
        as_of_fn: object = None,
    ) -> None:
        if _GIT_REVISION.fullmatch(expected_fdai_revision) is None:
            raise ValueError("expected FDAI revision MUST be a full immutable revision")
        if _IDENTIFIER.fullmatch(expected_scenario_set_version) is None:
            raise ValueError("expected scenario set version MUST be canonical")
        self._revision = expected_fdai_revision
        self._scenario = expected_scenario_set_version
        self._causal_receipt_verifier = causal_receipt_verifier
        self._unit_verifier = unit_verifier
        self._policy = policy or OperationalPromotionPolicy()
        self._as_of_fn = as_of_fn

    def evaluate(
        self,
        action_type: OntologyActionType,
        batch: OperationalPromotionBatch,
    ) -> OperationalPromotionReceipt:
        records = _latest_records(batch.records)
        sample_count = len(records)
        benchmark_samples = sum(
            record.cohort is PromotionEvidenceCohort.FROZEN_BENCHMARK for record in records
        )
        live_shadow_samples = sum(
            record.cohort is PromotionEvidenceCohort.LIVE_SHADOW for record in records
        )
        correct_count = sum(record.correct for record in records)
        policy_escapes = sum(record.policy_escape for record in records)
        executed = tuple(record for record in records if record.executed)
        rollback_count = sum(record.rolled_back for record in executed)
        recurrence_complete = tuple(
            record for record in executed if record.recurrence_window_complete
        )
        recurrence_incomplete = len(executed) - len(recurrence_complete)
        recurrence_count = sum(record.recurrence for record in recurrence_complete)
        simulation_review_count = sum(record.simulation_requires_review for record in records)
        accuracy = correct_count / sample_count if sample_count else 0.0
        accuracy_ci_lower, accuracy_ci_upper = _wilson_interval(
            correct_count,
            sample_count,
        )
        rollback_rate = rollback_count / len(executed) if executed else 0.0
        recurrence_rate = (
            recurrence_count / len(recurrence_complete) if recurrence_complete else 0.0
        )
        simulation_review_rate = simulation_review_count / sample_count if sample_count else 0.0
        benchmark = tuple(
            record
            for record in records
            if record.cohort is PromotionEvidenceCohort.FROZEN_BENCHMARK
        )
        live = tuple(
            record for record in records if record.cohort is PromotionEvidenceCohort.LIVE_SHADOW
        )
        benchmark_correct = sum(record.correct for record in benchmark)
        live_correct = sum(record.correct for record in live)
        benchmark_accuracy = benchmark_correct / len(benchmark) if benchmark else 0.0
        live_accuracy = live_correct / len(live) if live else 0.0
        benchmark_ci_lower, benchmark_ci_upper = _wilson_interval(benchmark_correct, len(benchmark))
        live_ci_lower, live_ci_upper = _wilson_interval(live_correct, len(live))
        observed = [record.observed_at for record in live]
        observation_days = (
            (max(observed) - min(observed)).total_seconds() / 86400.0 if observed else 0.0
        )
        live_observation_days = len({record.observed_at.astimezone(UTC).date() for record in live})
        minimum_rank = _EVIDENCE_RANK[self._policy.min_causal_evidence_grade]
        causal_evidence_failures = sum(
            _EVIDENCE_RANK[record.causal_receipt.evidence_grade] < minimum_rank
            or not self._causal_receipt_verifier.verify(record.causal_receipt)
            for record in records
        )
        unverified_units = sum(not self._unit_verifier.verify(record) for record in records)

        gate = action_type.promotion_gate
        gaps: list[str] = []
        if batch.fdai_revision != self._revision:
            gaps.append("fdai_revision_mismatch")
        if batch.scenario_set_version != self._scenario:
            gaps.append("scenario_set_version_mismatch")
        if batch.action_type_name != action_type.name:
            gaps.append("action_type_mismatch")
        if batch.action_type_version != action_type.version:
            gaps.append("action_type_version_mismatch")
        if batch.action_type_digest != _action_type_digest(action_type):
            gaps.append("action_type_digest_mismatch")
        if batch.sealed_at > self._as_of():
            gaps.append("batch_sealed_in_future")
        if sample_count < gate.min_samples:
            gaps.append(f"sample_count={sample_count}<min_samples={gate.min_samples}")
        if live_observation_days < gate.min_shadow_days:
            gaps.append(
                f"live_observation_days={live_observation_days}"
                f"<min_shadow_days={gate.min_shadow_days}"
            )
        if accuracy < gate.min_accuracy:
            gaps.append(f"accuracy={accuracy:.3f}<min_accuracy={gate.min_accuracy}")
        if accuracy_ci_lower < gate.min_accuracy:
            gaps.append(
                f"accuracy_ci_lower={accuracy_ci_lower:.3f}<min_accuracy={gate.min_accuracy}"
            )
        if benchmark_ci_lower < gate.min_accuracy:
            gaps.append(
                f"benchmark_accuracy_ci_lower={benchmark_ci_lower:.3f}"
                f"<min_accuracy={gate.min_accuracy}"
            )
        if live_ci_lower < gate.min_accuracy:
            gaps.append(
                f"live_shadow_accuracy_ci_lower={live_ci_lower:.3f}"
                f"<min_accuracy={gate.min_accuracy}"
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
        if not executed:
            gaps.append("no_executed_samples")
        if not recurrence_complete:
            gaps.append("no_complete_recurrence_windows")
        if recurrence_incomplete:
            gaps.append(f"recurrence_incomplete_samples={recurrence_incomplete}")
        if simulation_review_rate > self._policy.max_simulation_review_rate:
            gaps.append(
                f"simulation_review_rate={simulation_review_rate:.3f}"
                f">max_simulation_review_rate={self._policy.max_simulation_review_rate:.3f}"
            )
        if causal_evidence_failures:
            gaps.append(f"causal_evidence_failures={causal_evidence_failures}")
        if unverified_units:
            gaps.append(f"unverified_measurement_units={unverified_units}")

        return OperationalPromotionReceipt(
            fdai_revision=batch.fdai_revision,
            scenario_set_version=batch.scenario_set_version,
            action_type_name=batch.action_type_name,
            action_type_version=batch.action_type_version,
            action_type_digest=batch.action_type_digest,
            evidence_digest=batch.content_digest,
            observation_days=round(observation_days, 3),
            live_observation_days=live_observation_days,
            sample_count=sample_count,
            benchmark_samples=benchmark_samples,
            live_shadow_samples=live_shadow_samples,
            correct_count=correct_count,
            accuracy=round(accuracy, 4),
            accuracy_ci_lower=round(accuracy_ci_lower, 4),
            accuracy_ci_upper=round(accuracy_ci_upper, 4),
            benchmark_accuracy=round(benchmark_accuracy, 4),
            benchmark_accuracy_ci_lower=round(benchmark_ci_lower, 4),
            benchmark_accuracy_ci_upper=round(benchmark_ci_upper, 4),
            live_shadow_accuracy=round(live_accuracy, 4),
            live_shadow_accuracy_ci_lower=round(live_ci_lower, 4),
            live_shadow_accuracy_ci_upper=round(live_ci_upper, 4),
            policy_escapes=policy_escapes,
            rollback_rate=round(rollback_rate, 4),
            recurrence_rate=round(recurrence_rate, 4),
            executed_samples=len(executed),
            recurrence_complete_samples=len(recurrence_complete),
            recurrence_incomplete_samples=recurrence_incomplete,
            simulation_review_rate=round(simulation_review_rate, 4),
            causal_evidence_failures=causal_evidence_failures,
            ready=not gaps,
            gaps=tuple(gaps),
        )

    def _as_of(self) -> datetime:
        if self._as_of_fn is None:
            return datetime.now(tz=UTC)
        value = self._as_of_fn()  # type: ignore[operator]
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise TypeError("operational promotion as_of_fn MUST return aware datetime")
        return value


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _digest(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _action_type_digest(action_type: OntologyActionType) -> str:
    value = action_type.model_dump(mode="json", exclude={"provenance"}, exclude_none=True)
    return _digest(value)


def _latest_records(
    records: tuple[OperationalPromotionRecord, ...],
) -> tuple[OperationalPromotionRecord, ...]:
    latest: dict[str, OperationalPromotionRecord] = {}
    for record in records:
        prior = latest.get(record.measurement_unit_id)
        if prior is None or record.audit_sequence > prior.audit_sequence:
            latest[record.measurement_unit_id] = record
    return tuple(sorted(latest.values(), key=lambda item: item.measurement_unit_id))


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
    "CausalPromotionReceipt",
    "CausalPromotionReceiptVerifier",
    "OperationalPromotionBatch",
    "OperationalPromotionEvaluator",
    "OperationalPromotionPolicy",
    "OperationalPromotionReceipt",
    "OperationalPromotionRecord",
    "OperationalPromotionUnitVerifier",
    "PromotionEvidenceCohort",
]
