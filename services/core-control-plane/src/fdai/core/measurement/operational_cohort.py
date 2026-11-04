"""Deterministic aggregation for prospective operational cohort evidence.

The reducer accepts only repository-safe digests and numeric observations. It
does not read providers, assign an arm, mint evidence receipts, or grant claim
eligibility. A protected delivery adapter owns source authentication and an
independent verifier owns admission.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai_service_contracts.baseline_cohort import (
    CohortArm,
    CohortArmFacts,
    CohortGuardOutcome,
    CohortMeasurementBasisKind,
    CohortMetricEstimate,
)
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.measurement.cohort_claim_policy import CohortClaimPolicy

_BOOTSTRAP_RESAMPLES = 10_000


@dataclass(frozen=True, slots=True)
class OperationalMetricObservation:
    """One source-authenticated numeric contribution to a cohort metric."""

    metric_id: str
    observation_digest: str
    source_cluster_digest: str
    value: float
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_digest(self.observation_digest, "observation_digest")
        _require_digest(self.source_cluster_digest, "source_cluster_digest")
        if not self.metric_id:
            raise ValueError("operational metric id MUST be non-empty")
        if not math.isfinite(self.value) or self.value < 0:
            raise ValueError("operational metric value MUST be finite and non-negative")
        _require_aware(self.observed_at, "operational metric observed_at")


@dataclass(frozen=True, slots=True)
class OperationalGuardObservation:
    """One source-authenticated zero-threshold guard disposition."""

    guard_id: str
    observation_digest: str
    source_cluster_digest: str
    breached: bool
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_digest(self.observation_digest, "observation_digest")
        _require_digest(self.source_cluster_digest, "source_cluster_digest")
        if not self.guard_id:
            raise ValueError("operational guard id MUST be non-empty")
        if not isinstance(self.breached, bool):
            raise ValueError("operational guard breached MUST be boolean")
        _require_aware(self.observed_at, "operational guard observed_at")


@dataclass(frozen=True, slots=True)
class OperationalCohortArmBatch:
    """One preassigned arm window containing no raw operational identifiers."""

    arm: CohortArm
    fdai_revision: str
    window_start: datetime
    window_end: datetime
    synthetic: bool
    metrics: tuple[OperationalMetricObservation, ...]
    guards: tuple[OperationalGuardObservation, ...]

    def __post_init__(self) -> None:
        start = _require_aware(self.window_start, "cohort window_start")
        end = _require_aware(self.window_end, "cohort window_end")
        if end <= start:
            raise ValueError("cohort observation window MUST be positive")
        if not isinstance(self.synthetic, bool):
            raise ValueError("cohort synthetic marker MUST be boolean")


def aggregate_operational_cohort_arm(
    batch: OperationalCohortArmBatch,
    policy: CohortClaimPolicy,
) -> CohortArmFacts:
    """Aggregate one arm under a trusted frozen operational protocol.

    Repeated rows sharing an independence key contribute once. A conflicting
    correction for the same key fails closed rather than selecting a convenient
    value. Required measures may keep different natural denominators; the arm
    sample count is their minimum effective size.
    """

    window_seconds = (
        batch.window_end.astimezone(UTC) - batch.window_start.astimezone(UTC)
    ).total_seconds()
    if window_seconds > policy.maximum_window_seconds:
        raise ValueError("cohort observation window exceeds the frozen protocol")

    metric_rows = _deduplicate_metrics(batch.metrics, batch)
    guard_rows = _deduplicate_guards(batch.guards, batch)
    methods = dict(policy.interval_methods)

    metrics: list[CohortMetricEstimate] = []
    metric_sizes: dict[str, int] = {}
    for metric_id in policy.required_metric_ids:
        metric_rows_for_id = metric_rows.get(metric_id, ())
        metric_sizes[metric_id] = len(metric_rows_for_id)
        if not metric_rows_for_id:
            continue
        values = tuple(row.value for row in metric_rows_for_id)
        method = methods[metric_id]
        absolute, lower, upper = _estimate(metric_id, values, method)
        metrics.append(
            CohortMetricEstimate(
                metric_id=metric_id,
                absolute_value=absolute,
                sample_size=len(values),
                lower_bound=lower,
                upper_bound=upper,
            )
        )

    guards: list[CohortGuardOutcome] = []
    guard_sizes: dict[str, int] = {}
    for guard_id in policy.required_guard_ids:
        guard_rows_for_id = guard_rows.get(guard_id, ())
        guard_sizes[guard_id] = len(guard_rows_for_id)
        if not guard_rows_for_id:
            continue
        breached_count = sum(row.breached for row in guard_rows_for_id)
        observed = _zero_threshold_basis_points(
            breached_count,
            len(guard_rows_for_id),
        )
        guards.append(
            CohortGuardOutcome(
                guard_id=guard_id,
                observed_basis_points=observed,
                sample_size=len(guard_rows_for_id),
                breached=observed > 0,
            )
        )

    sizes = (*metric_sizes.values(), *guard_sizes.values())
    effective_sample_size = min(sizes, default=0)
    provenance = _provenance_digest(metric_rows, guard_rows)
    report = {
        "arm": batch.arm.value,
        "fdai_revision": batch.fdai_revision,
        "measurement_protocol_digest": policy.measurement_protocol_digest,
        "metric_sizes": metric_sizes,
        "guard_sizes": guard_sizes,
        "window_start": batch.window_start.astimezone(UTC).isoformat(),
        "window_end": batch.window_end.astimezone(UTC).isoformat(),
        "provenance_digest": provenance,
    }
    return CohortArmFacts(
        arm=batch.arm,
        measurement_basis_kind=CohortMeasurementBasisKind(policy.measurement_basis_kind),
        measurement_protocol_version=policy.measurement_protocol_version,
        measurement_protocol_digest=policy.measurement_protocol_digest,
        fdai_revision=batch.fdai_revision,
        report_digest=content_digest(report),
        provenance_digest=provenance,
        sample_count=effective_sample_size,
        synthetic=batch.synthetic,
        metrics_complete=all(metric_sizes.values()),
        provenance_complete=True,
        metrics=tuple(metrics),
        guards=tuple(guards),
    )


def _deduplicate_metrics(
    observations: Iterable[OperationalMetricObservation],
    batch: OperationalCohortArmBatch,
) -> dict[str, tuple[OperationalMetricObservation, ...]]:
    grouped: dict[str, dict[str, OperationalMetricObservation]] = {}
    for observation in observations:
        _require_in_window(observation.observed_at, batch)
        current = grouped.setdefault(observation.metric_id, {}).get(
            observation.source_cluster_digest
        )
        if current is not None and current != observation:
            raise ValueError("conflicting metric observations share one independence key")
        grouped[observation.metric_id][observation.source_cluster_digest] = observation
    return {
        metric_id: tuple(rows[key] for key in sorted(rows)) for metric_id, rows in grouped.items()
    }


def _deduplicate_guards(
    observations: Iterable[OperationalGuardObservation],
    batch: OperationalCohortArmBatch,
) -> dict[str, tuple[OperationalGuardObservation, ...]]:
    grouped: dict[str, dict[str, OperationalGuardObservation]] = {}
    for observation in observations:
        _require_in_window(observation.observed_at, batch)
        current = grouped.setdefault(observation.guard_id, {}).get(
            observation.source_cluster_digest
        )
        if current is not None and current != observation:
            raise ValueError("conflicting guard observations share one independence key")
        grouped[observation.guard_id][observation.source_cluster_digest] = observation
    return {
        guard_id: tuple(rows[key] for key in sorted(rows)) for guard_id, rows in grouped.items()
    }


def _estimate(
    metric_id: str,
    values: tuple[float, ...],
    method: str,
) -> tuple[float, float, float]:
    mean = sum(values) / len(values)
    if method == "wilson_95":
        if any(value not in (0.0, 1.0) for value in values):
            raise ValueError(f"{metric_id} Wilson observations MUST be zero or one")
        lower, upper = _wilson_interval(sum(values), len(values))
        return mean, lower, upper
    if method == "deterministic_bootstrap_95":
        lower, upper = _bootstrap_interval(metric_id, values)
        return mean, lower, upper
    raise ValueError(f"unsupported cohort interval method: {method}")


def _zero_threshold_basis_points(breached_count: int, sample_size: int) -> int:
    """Preserve any observed zero-threshold breach after basis-point scaling."""

    return math.ceil(breached_count * 10_000 / sample_size)


def _wilson_interval(successes: float, sample_size: int) -> tuple[float, float]:
    z = 1.959963984540054
    proportion = successes / sample_size
    denominator = 1 + z * z / sample_size
    centre = (proportion + z * z / (2 * sample_size)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / sample_size + z * z / (4 * sample_size * sample_size)
        )
        / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _bootstrap_interval(metric_id: str, values: tuple[float, ...]) -> tuple[float, float]:
    material = content_digest({"metric_id": metric_id, "values": values})
    sample_size = len(values)
    means = sorted(
        sum(
            values[_bootstrap_index(material, resample, draw, sample_size)]
            for draw in range(sample_size)
        )
        / sample_size
        for resample in range(_BOOTSTRAP_RESAMPLES)
    )
    return means[249], means[9_749]


def _bootstrap_index(material: str, resample: int, draw: int, sample_size: int) -> int:
    digest = hashlib.sha256(f"{material}:{resample}:{draw}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % sample_size


def _chunked_merkle_digests(digests: list[str], *, chunk_size: int = 64) -> list[str]:
    return [
        content_digest(digests[idx : idx + chunk_size])
        for idx in range(0, len(digests), chunk_size)
    ]


def _provenance_digest(
    metrics: Mapping[str, tuple[OperationalMetricObservation, ...]],
    guards: Mapping[str, tuple[OperationalGuardObservation, ...]],
) -> str:
    metric_lists = {
        key: [row.observation_digest for row in rows] for key, rows in sorted(metrics.items())
    }
    guard_lists = {
        key: [row.observation_digest for row in rows] for key, rows in sorted(guards.items())
    }
    total_digests = sum(len(v) for v in metric_lists.values()) + sum(
        len(v) for v in guard_lists.values()
    )
    if total_digests <= 512:
        return content_digest(
            {
                "metric_observation_digests": metric_lists,
                "guard_observation_digests": guard_lists,
            }
        )
    return content_digest(
        {
            "merkle_schema_version": "2.0.0",
            "metric_chunk_digests": {
                key: _chunked_merkle_digests(rows) for key, rows in metric_lists.items()
            },
            "guard_chunk_digests": {
                key: _chunked_merkle_digests(rows) for key, rows in guard_lists.items()
            },
        }
    )


def _require_in_window(
    observed_at: datetime,
    batch: OperationalCohortArmBatch,
) -> None:
    observed = observed_at.astimezone(UTC)
    if not batch.window_start.astimezone(UTC) <= observed <= batch.window_end.astimezone(UTC):
        raise ValueError("cohort observation falls outside its frozen window")


def _require_digest(value: str, name: str) -> str:
    if not value.startswith("sha256:") or len(value) != 71:
        raise ValueError(f"{name} MUST be a SHA-256 digest")
    return value


def _require_aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST include a timezone")
    return value.astimezone(UTC)


__all__ = [
    "OperationalCohortArmBatch",
    "OperationalGuardObservation",
    "OperationalMetricObservation",
    "aggregate_operational_cohort_arm",
]
