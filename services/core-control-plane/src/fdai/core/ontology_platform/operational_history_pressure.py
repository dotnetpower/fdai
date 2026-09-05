"""Deterministic storage-pressure degradation for operational history."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class StoragePressureLevel(StrEnum):
    """Bounded storage-pressure severity."""

    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    HARD = "hard"


@dataclass(frozen=True, slots=True)
class StoragePressurePolicy:
    """Deployment-owned storage thresholds and hard query-hold ceiling."""

    warning_bytes: int
    critical_bytes: int
    hard_bytes: int
    max_purge_backlog: int
    max_projection_lag: int

    def __post_init__(self) -> None:
        if not 0 < self.warning_bytes < self.critical_bytes < self.hard_bytes:
            raise ValueError("storage pressure byte thresholds MUST increase")
        if self.max_purge_backlog < 1 or self.max_projection_lag < 1:
            raise ValueError("storage pressure backlog and lag thresholds MUST be positive")


@dataclass(frozen=True, slots=True)
class StoragePressureAssessment:
    """Deterministic degradation posture under measured storage pressure."""

    level: StoragePressureLevel
    archive_priority: bool
    reduce_nonessential_collection: bool
    apply_source_admission_budget: bool
    hold_completeness_dependent_work: bool
    projected_exhaustion_seconds: int | None


def assess_storage_pressure(
    policy: StoragePressurePolicy,
    *,
    database_bytes: int,
    purge_backlog: int,
    projection_lag: int,
    growth_bytes_per_second: int | None,
) -> StoragePressureAssessment:
    """Reduce measured capacity to a monotonic fail-closed degradation posture."""

    if min(database_bytes, purge_backlog, projection_lag) < 0:
        raise ValueError("storage pressure measurements MUST be non-negative")
    if growth_bytes_per_second is not None and growth_bytes_per_second < 0:
        raise ValueError("storage growth rate MUST be non-negative")
    hard = (
        database_bytes >= policy.hard_bytes
        or purge_backlog > policy.max_purge_backlog
        or projection_lag > policy.max_projection_lag
    )
    if hard:
        level = StoragePressureLevel.HARD
    elif database_bytes >= policy.critical_bytes:
        level = StoragePressureLevel.CRITICAL
    elif database_bytes >= policy.warning_bytes:
        level = StoragePressureLevel.WARNING
    else:
        level = StoragePressureLevel.NORMAL
    exhaustion = None
    if growth_bytes_per_second:
        exhaustion = max(0, (policy.hard_bytes - database_bytes) // growth_bytes_per_second)
    return StoragePressureAssessment(
        level=level,
        archive_priority=level is not StoragePressureLevel.NORMAL,
        reduce_nonessential_collection=level
        in {
            StoragePressureLevel.CRITICAL,
            StoragePressureLevel.HARD,
        },
        apply_source_admission_budget=level is StoragePressureLevel.HARD,
        hold_completeness_dependent_work=level is StoragePressureLevel.HARD,
        projected_exhaustion_seconds=exhaustion,
    )


__all__ = [
    "StoragePressureAssessment",
    "StoragePressureLevel",
    "StoragePressurePolicy",
    "assess_storage_pressure",
]
