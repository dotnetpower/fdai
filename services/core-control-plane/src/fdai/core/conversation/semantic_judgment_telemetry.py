"""Content-free telemetry projection for semantic judgment receipts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentDisposition,
    SemanticJudgmentReceipt,
    SemanticJudgmentTier,
)

_MAX_RECEIPTS = 10_000


@dataclass(frozen=True, slots=True)
class SemanticJudgmentTelemetrySample:
    """One content-free semantic outcome suitable for metrics and audit correlation."""

    receipt_digest: str
    profile_id: str
    profile_version: str
    tier: SemanticJudgmentTier | None
    model_config_digest: str | None
    prompt_digest: str | None
    confidence: float | None
    latency_ms: int
    outcome: SemanticJudgmentDisposition
    abstained: bool
    execution_authority: Literal[False] = False


@dataclass(frozen=True, slots=True)
class SemanticJudgmentTelemetrySummary:
    """Replay-stable semantic metrics for one profile revision."""

    profile_id: str
    profile_version: str
    total_count: int
    abstention_count: int
    abstention_rate: float
    outcome_counts: tuple[tuple[str, int], ...]
    tier_counts: tuple[tuple[str, int], ...]
    samples: tuple[SemanticJudgmentTelemetrySample, ...]
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority:
            raise ValueError("semantic judgment telemetry MUST NOT grant execution authority")


def summarize_semantic_judgments(
    receipts: Sequence[SemanticJudgmentReceipt],
) -> SemanticJudgmentTelemetrySummary:
    """Project bounded receipts without retaining utterance or context identities."""

    if not receipts:
        raise ValueError("semantic judgment telemetry requires at least one receipt")
    if len(receipts) > _MAX_RECEIPTS:
        raise ValueError(f"semantic judgment telemetry accepts at most {_MAX_RECEIPTS} receipts")

    profiles = {(receipt.profile_id, receipt.profile_version) for receipt in receipts}
    if len(profiles) != 1:
        raise ValueError("semantic judgment telemetry requires one profile revision")
    receipt_digests = [receipt.receipt_digest for receipt in receipts]
    if len(receipt_digests) != len(set(receipt_digests)):
        raise ValueError("semantic judgment telemetry receipt digests MUST be unique")

    samples = tuple(
        sorted(
            (_sample(receipt) for receipt in receipts),
            key=lambda sample: sample.receipt_digest,
        )
    )
    outcomes = Counter(sample.outcome.value for sample in samples)
    tiers = Counter(sample.tier.value if sample.tier is not None else "none" for sample in samples)
    abstention_count = sum(sample.abstained for sample in samples)
    profile_id, profile_version = profiles.pop()
    return SemanticJudgmentTelemetrySummary(
        profile_id=profile_id,
        profile_version=profile_version,
        total_count=len(samples),
        abstention_count=abstention_count,
        abstention_rate=abstention_count / len(samples),
        outcome_counts=tuple(sorted(outcomes.items())),
        tier_counts=tuple(sorted(tiers.items())),
        samples=samples,
    )


def _sample(receipt: SemanticJudgmentReceipt) -> SemanticJudgmentTelemetrySample:
    return SemanticJudgmentTelemetrySample(
        receipt_digest=receipt.receipt_digest,
        profile_id=receipt.profile_id,
        profile_version=receipt.profile_version,
        tier=receipt.tier,
        model_config_digest=receipt.model_config_digest,
        prompt_digest=receipt.prompt_digest,
        confidence=receipt.confidence,
        latency_ms=receipt.latency_ms,
        outcome=receipt.disposition,
        abstained=receipt.disposition is not SemanticJudgmentDisposition.ACCEPTED,
    )


__all__ = [
    "SemanticJudgmentTelemetrySample",
    "SemanticJudgmentTelemetrySummary",
    "summarize_semantic_judgments",
]
