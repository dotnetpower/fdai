"""Versioned content-free latency evidence for ChatOps qualification."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.core.conversation_assurance.quality_trace import trace_set_digest

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class LatencyStage(StrEnum):
    TIME_TO_FIRST_TOKEN = "time_to_first_token"  # noqa: S105 - metric name
    TERMINAL_ANSWER = "terminal_answer"
    DETERMINISTIC_VERIFICATION = "deterministic_verification"
    CHANNEL_ACKNOWLEDGEMENT = "channel_acknowledgement"
    COMPLETE_DELIVERY = "complete_delivery"


class LatencyEnvironment(StrEnum):
    PR_REGRESSION = "pr_regression"
    LIVE_CANARY = "live_canary"
    RELEASE = "release"


class LatencySampleOutcome(StrEnum):
    COMPLETED = "completed"
    CORRECTED = "corrected"
    ABSTAINED = "abstained"
    UNSUPPORTED = "unsupported"
    FALLBACK = "fallback"
    TRUNCATED = "truncated"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class LatencyStageSlo:
    stage: LatencyStage
    environment: LatencyEnvironment
    minimum_samples: int
    p50_ceiling_ms: int
    p95_ceiling_ms: int
    p99_ceiling_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.stage, LatencyStage) or not isinstance(
            self.environment, LatencyEnvironment
        ):
            raise ValueError("latency SLO stage and environment MUST use contract enums")
        values = (
            self.minimum_samples,
            self.p50_ceiling_ms,
            self.p95_ceiling_ms,
            self.p99_ceiling_ms,
        )
        if any(type(value) is not int or value < 1 for value in values):
            raise ValueError("latency SLO floors and ceilings MUST be positive integers")
        if not self.p50_ceiling_ms <= self.p95_ceiling_ms <= self.p99_ceiling_ms:
            raise ValueError("latency SLO percentile ceilings MUST be ordered")


@dataclass(frozen=True, slots=True)
class ChatOpsLatencyContract:
    version: str
    stages: tuple[LatencyStageSlo, ...]

    def __post_init__(self) -> None:
        _token(self.version, "latency contract version")
        if tuple(item.stage for item in self.stages) != tuple(LatencyStage):
            raise ValueError("latency contract MUST define every stage once in enum order")

    @property
    def content_digest(self) -> str:
        return _digest(
            {
                "version": self.version,
                "stages": [
                    {
                        "stage": item.stage.value,
                        "environment": item.environment.value,
                        "minimum_samples": item.minimum_samples,
                        "p50_ceiling_ms": item.p50_ceiling_ms,
                        "p95_ceiling_ms": item.p95_ceiling_ms,
                        "p99_ceiling_ms": item.p99_ceiling_ms,
                    }
                    for item in self.stages
                ],
            }
        )


@dataclass(frozen=True, slots=True)
class LatencySample:
    stage: LatencyStage
    environment: LatencyEnvironment
    observed_at: str
    duration_ms: float
    timestamp_authority: str
    trace_digest: str
    provenance_digest: str
    outcome: LatencySampleOutcome

    def __post_init__(self) -> None:
        if (
            not isinstance(self.stage, LatencyStage)
            or not isinstance(self.environment, LatencyEnvironment)
            or not isinstance(self.outcome, LatencySampleOutcome)
        ):
            raise ValueError(
                "latency sample stage, environment, and outcome MUST use contract enums"
            )
        _timestamp(self.observed_at, "latency sample observed_at")
        if (
            isinstance(self.duration_ms, bool)
            or not isinstance(self.duration_ms, (int, float))
            or not math.isfinite(self.duration_ms)
            or self.duration_ms < 0
        ):
            raise ValueError("latency sample duration_ms MUST be finite and non-negative")
        _token(self.timestamp_authority, "latency sample timestamp_authority")
        _sha256(self.trace_digest, "latency sample trace_digest")
        _sha256(self.provenance_digest, "latency sample provenance_digest")


@dataclass(frozen=True, slots=True)
class LatencyStageReceipt:
    """Authoritative stage-owner timing before conversion to benchmark evidence."""

    stage: LatencyStage
    environment: LatencyEnvironment
    observed_at: str
    started_monotonic_ns: int
    completed_monotonic_ns: int
    timestamp_authority: str
    trace_digest: str
    provenance_digest: str
    outcome: LatencySampleOutcome

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (self.started_monotonic_ns, self.completed_monotonic_ns)
        ):
            raise ValueError("stage receipt monotonic values MUST be non-negative integers")
        if self.completed_monotonic_ns < self.started_monotonic_ns:
            raise ValueError("stage receipt completion MUST NOT precede its start")
        LatencySample(
            stage=self.stage,
            environment=self.environment,
            observed_at=self.observed_at,
            duration_ms=0.0,
            timestamp_authority=self.timestamp_authority,
            trace_digest=self.trace_digest,
            provenance_digest=self.provenance_digest,
            outcome=self.outcome,
        )


@dataclass(frozen=True, slots=True)
class LatencyBenchmarkBatch:
    run_id: str
    source_revision: str
    started_at: str
    completed_at: str
    samples: tuple[LatencySample, ...]

    def __post_init__(self) -> None:
        _token(self.run_id, "latency benchmark run_id")
        if _REVISION.fullmatch(self.source_revision) is None:
            raise ValueError("latency benchmark source_revision MUST be a full git object id")
        started = _timestamp(self.started_at, "latency benchmark started_at")
        completed = _timestamp(self.completed_at, "latency benchmark completed_at")
        if completed < started:
            raise ValueError("latency benchmark completed_at MUST NOT precede started_at")
        if len(self.samples) > 100_000:
            raise ValueError("latency benchmark samples MUST contain at most 100000 records")
        if any(not isinstance(sample, LatencySample) for sample in self.samples):
            raise ValueError("latency benchmark samples MUST use LatencySample records")
        if any(
            not started <= _timestamp(sample.observed_at, "latency sample observed_at") <= completed
            for sample in self.samples
        ):
            raise ValueError("latency sample observed_at MUST be inside the benchmark window")
        identities = tuple((sample.stage, sample.trace_digest) for sample in self.samples)
        if len(identities) != len(set(identities)):
            raise ValueError("latency samples MUST be unique by stage and trace_digest")


@dataclass(frozen=True, slots=True)
class LatencyStageEvidence:
    stage: LatencyStage
    environment: LatencyEnvironment
    minimum_samples: int
    sample_count: int
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    p50_ceiling_ms: int
    p95_ceiling_ms: int
    p99_ceiling_ms: int
    timestamp_authorities: tuple[str, ...]
    outcome_counts: tuple[tuple[LatencySampleOutcome, int], ...]
    passed: bool
    gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChatOpsLatencyEvidence:
    run_digest: str
    source_revision: str
    contract_version: str
    contract_digest: str
    sample_manifest_digest: str
    trace_count: int
    trace_set_digest: str
    started_at: str
    completed_at: str
    stages: tuple[LatencyStageEvidence, ...]
    latency_slo_met: bool

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "1.0.0",
            "evidence_kind": "chatops_latency_benchmark",
            "qualification_authority": False,
            "complete_trace_claimed": False,
            "run_digest": self.run_digest,
            "source_revision": self.source_revision,
            "contract_version": self.contract_version,
            "contract_digest": self.contract_digest,
            "sample_manifest_digest": self.sample_manifest_digest,
            "trace_count": self.trace_count,
            "trace_set_digest": self.trace_set_digest,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "latency_slo_met": self.latency_slo_met,
            "stages": [
                {
                    "stage": item.stage.value,
                    "environment": item.environment.value,
                    "minimum_samples": item.minimum_samples,
                    "sample_count": item.sample_count,
                    "p50_ms": item.p50_ms,
                    "p95_ms": item.p95_ms,
                    "p99_ms": item.p99_ms,
                    "p50_ceiling_ms": item.p50_ceiling_ms,
                    "p95_ceiling_ms": item.p95_ceiling_ms,
                    "p99_ceiling_ms": item.p99_ceiling_ms,
                    "timestamp_authorities": list(item.timestamp_authorities),
                    "outcome_counts": {
                        outcome.value: count for outcome, count in item.outcome_counts
                    },
                    "passed": item.passed,
                    "gaps": list(item.gaps),
                }
                for item in self.stages
            ],
        }
        payload["content_digest"] = _digest(payload)
        return payload


def reduce_latency_benchmark(
    batch: LatencyBenchmarkBatch,
    *,
    contract: ChatOpsLatencyContract | None = None,
) -> ChatOpsLatencyEvidence:
    """Reduce premeasured samples without treating a digest as trace completeness."""

    effective_contract = contract or CHATOPS_LATENCY_CONTRACT_V1
    stage_evidence: list[LatencyStageEvidence] = []
    for slo in effective_contract.stages:
        samples = tuple(sample for sample in batch.samples if sample.stage is slo.stage)
        if any(sample.environment is not slo.environment for sample in samples):
            raise ValueError(f"latency stage {slo.stage.value} uses the wrong environment")
        durations = tuple(float(sample.duration_ms) for sample in samples)
        p50 = _percentile(durations, 0.50)
        p95 = _percentile(durations, 0.95)
        p99 = _percentile(durations, 0.99)
        outcomes = Counter(sample.outcome for sample in samples)
        gaps: list[str] = []
        if len(samples) < slo.minimum_samples:
            gaps.append(f"sample_count={len(samples)}<minimum_samples={slo.minimum_samples}")
        for name, observed, ceiling in (
            ("p50", p50, slo.p50_ceiling_ms),
            ("p95", p95, slo.p95_ceiling_ms),
            ("p99", p99, slo.p99_ceiling_ms),
        ):
            if observed is not None and observed > ceiling:
                gaps.append(f"{name}_ms={observed}>ceiling_ms={ceiling}")
        if outcomes[LatencySampleOutcome.TIMED_OUT]:
            gaps.append(f"timed_out_samples={outcomes[LatencySampleOutcome.TIMED_OUT]}")
        stage_evidence.append(
            LatencyStageEvidence(
                stage=slo.stage,
                environment=slo.environment,
                minimum_samples=slo.minimum_samples,
                sample_count=len(samples),
                p50_ms=p50,
                p95_ms=p95,
                p99_ms=p99,
                p50_ceiling_ms=slo.p50_ceiling_ms,
                p95_ceiling_ms=slo.p95_ceiling_ms,
                p99_ceiling_ms=slo.p99_ceiling_ms,
                timestamp_authorities=tuple(
                    sorted({sample.timestamp_authority for sample in samples})
                ),
                outcome_counts=tuple(
                    (outcome, outcomes[outcome]) for outcome in LatencySampleOutcome
                ),
                passed=not gaps,
                gaps=tuple(gaps),
            )
        )
    trace_digests = tuple(sorted({sample.trace_digest for sample in batch.samples}))
    return ChatOpsLatencyEvidence(
        run_digest=_digest(batch.run_id),
        source_revision=batch.source_revision,
        contract_version=effective_contract.version,
        contract_digest=effective_contract.content_digest,
        sample_manifest_digest=_sample_manifest_digest(batch.samples),
        trace_count=len(trace_digests),
        trace_set_digest=(trace_set_digest(trace_digests) if trace_digests else _digest([])),
        started_at=batch.started_at,
        completed_at=batch.completed_at,
        stages=tuple(stage_evidence),
        latency_slo_met=all(item.passed for item in stage_evidence),
    )


def latency_sample_from_stage_receipt(
    receipt: LatencyStageReceipt,
    *,
    contract: ChatOpsLatencyContract | None = None,
) -> LatencySample:
    """Derive duration only from the stage owner's monotonic receipt."""

    effective_contract = contract or CHATOPS_LATENCY_CONTRACT_V1
    slo = effective_contract.stages[tuple(LatencyStage).index(receipt.stage)]
    if receipt.environment is not slo.environment:
        raise ValueError("stage receipt environment does not match the installed contract")
    return LatencySample(
        stage=receipt.stage,
        environment=receipt.environment,
        observed_at=receipt.observed_at,
        duration_ms=(receipt.completed_monotonic_ns - receipt.started_monotonic_ns) / 1_000_000,
        timestamp_authority=receipt.timestamp_authority,
        trace_digest=receipt.trace_digest,
        provenance_digest=receipt.provenance_digest,
        outcome=receipt.outcome,
    )


def _percentile(samples: tuple[float, ...], quantile: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction), 3)


def _token(value: str, field: str) -> None:
    if _TOKEN.fullmatch(value) is None:
        raise ValueError(f"{field} MUST be a bounded portable token")


def _sha256(value: str, field: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{field} MUST be a lowercase SHA-256 digest")


def _timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{field} MUST be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} MUST include a timezone")
    return parsed


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _sample_manifest_digest(samples: tuple[LatencySample, ...]) -> str:
    return _digest(
        [
            {
                "stage": sample.stage.value,
                "environment": sample.environment.value,
                "observed_at": sample.observed_at,
                "duration_ms": float(sample.duration_ms),
                "timestamp_authority": sample.timestamp_authority,
                "trace_digest": sample.trace_digest,
                "provenance_digest": sample.provenance_digest,
                "outcome": sample.outcome.value,
            }
            for sample in sorted(
                samples,
                key=lambda item: (
                    tuple(LatencyStage).index(item.stage),
                    item.observed_at,
                    item.trace_digest,
                ),
            )
        ]
    )


CHATOPS_LATENCY_CONTRACT_V1 = ChatOpsLatencyContract(
    version="chatops-latency-v1",
    stages=(
        LatencyStageSlo(
            stage=LatencyStage.TIME_TO_FIRST_TOKEN,
            environment=LatencyEnvironment.LIVE_CANARY,
            minimum_samples=30,
            p50_ceiling_ms=1_000,
            p95_ceiling_ms=2_500,
            p99_ceiling_ms=5_000,
        ),
        LatencyStageSlo(
            stage=LatencyStage.TERMINAL_ANSWER,
            environment=LatencyEnvironment.RELEASE,
            minimum_samples=500,
            p50_ceiling_ms=8_000,
            p95_ceiling_ms=20_000,
            p99_ceiling_ms=30_000,
        ),
        LatencyStageSlo(
            stage=LatencyStage.DETERMINISTIC_VERIFICATION,
            environment=LatencyEnvironment.PR_REGRESSION,
            minimum_samples=100,
            p50_ceiling_ms=250,
            p95_ceiling_ms=750,
            p99_ceiling_ms=1_500,
        ),
        LatencyStageSlo(
            stage=LatencyStage.CHANNEL_ACKNOWLEDGEMENT,
            environment=LatencyEnvironment.LIVE_CANARY,
            minimum_samples=30,
            p50_ceiling_ms=1_000,
            p95_ceiling_ms=5_000,
            p99_ceiling_ms=9_000,
        ),
        LatencyStageSlo(
            stage=LatencyStage.COMPLETE_DELIVERY,
            environment=LatencyEnvironment.RELEASE,
            minimum_samples=500,
            p50_ceiling_ms=10_000,
            p95_ceiling_ms=25_000,
            p99_ceiling_ms=40_000,
        ),
    ),
)


__all__ = [
    "CHATOPS_LATENCY_CONTRACT_V1",
    "ChatOpsLatencyContract",
    "ChatOpsLatencyEvidence",
    "LatencyBenchmarkBatch",
    "LatencyEnvironment",
    "LatencySample",
    "LatencySampleOutcome",
    "LatencyStageReceipt",
    "LatencyStage",
    "LatencyStageEvidence",
    "LatencyStageSlo",
    "latency_sample_from_stage_receipt",
    "reduce_latency_benchmark",
]
