"""Reviewed metric concepts, aligned windows, and bounded causal evidence joins."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from fdai.core.detection.series import MetricSample
from fdai.core.rca.temporal_causality import (
    TemporalCausalClaim,
    TemporalCausalityAnalyzer,
    TemporalCausalityConfig,
    TemporalSeries,
)

from .topology_history import TopologyDiff


class MetricAggregation(StrEnum):
    SUM = "sum"
    AVERAGE = "average"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    COUNT = "count"


@dataclass(frozen=True, slots=True)
class MetricSemanticDefinition:
    """One reviewed concept resolved after language interpretation, never by phrase routing."""

    concept_id: str
    provider_metric: str
    canonical_unit: str
    aggregation: MetricAggregation
    description: str
    monotonic: bool = False

    def __post_init__(self) -> None:
        for name, value, maximum in (
            ("concept_id", self.concept_id, 128),
            ("provider_metric", self.provider_metric, 256),
            ("canonical_unit", self.canonical_unit, 64),
            ("description", self.description, 1_024),
        ):
            if not value or len(value) > maximum:
                raise ValueError(f"metric semantic {name} MUST be bounded and non-empty")


@dataclass(frozen=True, slots=True)
class MetricSemanticRegistry:
    """Content-addressed exact concept registry without natural-language aliases."""

    definitions: Mapping[str, MetricSemanticDefinition]
    digest: str

    @classmethod
    def build(
        cls,
        definitions: Sequence[MetricSemanticDefinition],
    ) -> MetricSemanticRegistry:
        by_id: dict[str, MetricSemanticDefinition] = {}
        for item in definitions:
            if item.concept_id in by_id:
                raise ValueError(f"duplicate metric concept {item.concept_id!r}")
            by_id[item.concept_id] = item
        if not by_id:
            raise ValueError("metric semantic registry MUST NOT be empty")
        body = [
            {
                "concept_id": item.concept_id,
                "provider_metric": item.provider_metric,
                "canonical_unit": item.canonical_unit,
                "aggregation": item.aggregation.value,
                "description": item.description,
                "monotonic": item.monotonic,
            }
            for item in sorted(by_id.values(), key=lambda item: item.concept_id)
        ]
        return cls(
            definitions=MappingProxyType(by_id),
            digest=_digest(body),
        )

    def resolve(self, concept_id: str) -> MetricSemanticDefinition:
        try:
            return self.definitions[concept_id]
        except KeyError as exc:
            raise KeyError(f"unknown metric concept {concept_id!r}") from exc


@dataclass(frozen=True, slots=True)
class MetricWindow:
    """One authoritative bounded series with explicit completeness evidence."""

    concept_id: str
    resource_id: str
    unit: str
    start: datetime
    end: datetime
    samples: tuple[MetricSample, ...]
    complete: bool
    evidence_refs: tuple[str, ...]
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None or self.start >= self.end:
            raise ValueError("metric window MUST have an aware positive interval")
        if len(self.samples) > 10_000:
            raise ValueError("metric window exceeds 10000 samples")
        timestamps = tuple(item.timestamp for item in self.samples)
        if timestamps != tuple(sorted(set(timestamps))):
            raise ValueError("metric window samples MUST be unique and ordered")
        if any(item.timestamp < self.start or item.timestamp > self.end for item in self.samples):
            raise ValueError("metric sample lies outside its window")
        if any(not math.isfinite(item.value) for item in self.samples):
            raise ValueError("metric window samples MUST be finite")
        if self.complete and self.missing_reason is not None:
            raise ValueError("complete metric window MUST NOT have a missing reason")
        if not self.complete and not self.missing_reason:
            raise ValueError("incomplete metric window MUST have a missing reason")
        if not self.evidence_refs:
            raise ValueError("metric window MUST cite evidence")


@dataclass(frozen=True, slots=True)
class MetricWindowComparison:
    """Equal-duration comparison that distinguishes observed zero from missing data."""

    baseline_value: float | None
    current_value: float | None
    absolute_change: float | None
    relative_change: float | None
    complete: bool
    reason: str | None
    evidence_refs: tuple[str, ...]


def compare_aligned_windows(
    baseline: MetricWindow,
    current: MetricWindow,
    *,
    aggregation: MetricAggregation,
) -> MetricWindowComparison:
    """Compare equal windows only when identities, units, and coverage align."""

    if baseline.concept_id != current.concept_id or baseline.resource_id != current.resource_id:
        raise ValueError("metric comparison identity mismatch")
    if baseline.unit != current.unit:
        raise ValueError("metric comparison unit mismatch")
    if (baseline.end - baseline.start) != (current.end - current.start):
        raise ValueError("metric comparison windows MUST have equal duration")
    evidence_refs = tuple(dict.fromkeys((*baseline.evidence_refs, *current.evidence_refs)))
    if not baseline.complete or not current.complete:
        reasons = sorted(
            {
                item.missing_reason or "incomplete"
                for item in (baseline, current)
                if not item.complete
            }
        )
        return MetricWindowComparison(
            baseline_value=None,
            current_value=None,
            absolute_change=None,
            relative_change=None,
            complete=False,
            reason="+".join(reasons),
            evidence_refs=evidence_refs,
        )
    baseline_value = _aggregate(baseline.samples, aggregation)
    current_value = _aggregate(current.samples, aggregation)
    absolute = current_value - baseline_value
    relative = None if baseline_value == 0.0 else absolute / abs(baseline_value)
    return MetricWindowComparison(
        baseline_value=baseline_value,
        current_value=current_value,
        absolute_change=absolute,
        relative_change=relative,
        complete=True,
        reason=None,
        evidence_refs=evidence_refs,
    )


class CausalJoinStatus(StrEnum):
    SUPPORTED = "supported"
    REFUTED = "refuted"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class CausalEvidenceJoin:
    """One bounded hypothesis disposition; chronology alone remains unresolved."""

    status: CausalJoinStatus
    temporal_claim: TemporalCausalClaim | None
    topology_diff_digest: str | None
    competing_explanations: tuple[str, ...]
    limitations: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.execution_authority:
            raise ValueError("causal evidence join MUST NOT grant execution authority")


def join_causal_evidence(
    *,
    cause: MetricWindow,
    effect: MetricWindow,
    topology_change: TopologyDiff | None,
    feature_cutoff: datetime,
    config: TemporalCausalityConfig,
    competing_explanations: Sequence[str],
) -> CausalEvidenceJoin:
    """Join complete aligned series and topology evidence without asserting mere chronology."""

    evidence_refs = tuple(dict.fromkeys((*cause.evidence_refs, *effect.evidence_refs)))
    limitations: list[str] = []
    if not cause.complete or not effect.complete:
        limitations.append("metric_window_incomplete")
    if topology_change is None:
        limitations.append("topology_change_unavailable")
    elif not topology_change.complete:
        limitations.append("topology_history_incomplete")
    if len(cause.samples) < 2 or len(effect.samples) < 2:
        limitations.append("insufficient_aligned_samples")
    if limitations:
        return CausalEvidenceJoin(
            status=CausalJoinStatus.UNRESOLVED,
            temporal_claim=None,
            topology_diff_digest=topology_change.digest if topology_change else None,
            competing_explanations=tuple(competing_explanations),
            limitations=tuple(limitations),
            evidence_refs=evidence_refs,
        )
    analyzer = TemporalCausalityAnalyzer(config)
    claim = analyzer.analyze(
        cause=TemporalSeries(metric=cause.concept_id, samples=cause.samples),
        effect=TemporalSeries(metric=effect.concept_id, samples=effect.samples),
        feature_cutoff=feature_cutoff,
        evidence_refs=evidence_refs,
    )
    if claim is None:
        status = CausalJoinStatus.UNRESOLVED
        limitations.append("insufficient_aligned_samples")
    elif claim.falsifiers:
        status = CausalJoinStatus.REFUTED
        limitations.extend(claim.falsifiers)
    else:
        status = CausalJoinStatus.SUPPORTED
    return CausalEvidenceJoin(
        status=status,
        temporal_claim=claim,
        topology_diff_digest=topology_change.digest if topology_change else None,
        competing_explanations=tuple(competing_explanations),
        limitations=tuple(limitations),
        evidence_refs=tuple(
            dict.fromkeys(
                (*evidence_refs, *(topology_change.evidence_refs if topology_change else ()))
            )
        ),
    )


class MetricWindowProvider(Protocol):
    """Read one authoritative metric concept after exact registry grounding."""

    async def read(
        self,
        *,
        definition: MetricSemanticDefinition,
        resource_id: str,
        start: datetime,
        end: datetime,
    ) -> MetricWindow: ...


def _aggregate(samples: Sequence[MetricSample], aggregation: MetricAggregation) -> float:
    values = [item.value for item in samples]
    if aggregation is MetricAggregation.COUNT:
        return float(len(values))
    if not values:
        return 0.0
    if aggregation is MetricAggregation.SUM:
        return math.fsum(values)
    if aggregation is MetricAggregation.AVERAGE:
        return math.fsum(values) / len(values)
    if aggregation is MetricAggregation.MINIMUM:
        return min(values)
    return max(values)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CausalEvidenceJoin",
    "CausalJoinStatus",
    "MetricAggregation",
    "MetricSemanticDefinition",
    "MetricSemanticRegistry",
    "MetricWindow",
    "MetricWindowComparison",
    "MetricWindowProvider",
    "compare_aligned_windows",
    "join_causal_evidence",
]
