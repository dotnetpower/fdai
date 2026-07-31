"""Immutable operational context values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fdai.shared.contracts.models import Autonomy


@dataclass(frozen=True, slots=True)
class SourceFreshness:
    """One source observation and its accepted age ceiling."""

    source: str
    observed_at: datetime
    max_age_seconds: int

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("SourceFreshness.source MUST be non-empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("SourceFreshness.observed_at MUST be timezone-aware")
        if self.max_age_seconds < 1:
            raise ValueError("SourceFreshness.max_age_seconds MUST be >= 1")


@dataclass(frozen=True, slots=True)
class OperationalContextEvidenceLink:
    """One typed graph edge retained without raw link properties."""

    link_type: str
    from_id: str
    to_id: str

    def __post_init__(self) -> None:
        if not self.link_type or not self.from_id or not self.to_id:
            raise ValueError("operational context evidence link fields MUST be non-empty")


@dataclass(frozen=True, slots=True)
class OperationalContextEvidencePath:
    """One deterministic shortest path from the target to a context object."""

    object_id: str
    object_type: str
    revision: int
    links: tuple[OperationalContextEvidenceLink, ...]

    def __post_init__(self) -> None:
        if not self.object_id or not self.object_type:
            raise ValueError("operational context evidence path identities MUST be non-empty")
        if self.revision < 0:
            raise ValueError("operational context evidence path revision MUST be >= 0")


@dataclass(frozen=True, slots=True)
class OperationalContextSnapshot:
    """Replay-stable semantic context at one decision cutoff."""

    snapshot_id: str
    target_resource_id: str
    cutoff: datetime
    recorded_at: datetime
    catalog_versions: tuple[tuple[str, str], ...]
    service_ids: tuple[str, ...]
    workload_ids: tuple[str, ...]
    objective_ids: tuple[str, ...]
    service_objective_ids: tuple[str, ...]
    recovery_objective_ids: tuple[str, ...]
    cost_objective_ids: tuple[str, ...]
    constraint_ids: tuple[str, ...]
    ownership_ids: tuple[str, ...]
    dependency_ids: tuple[str, ...]
    source_freshness: tuple[SourceFreshness, ...]
    evidence_links: tuple[OperationalContextEvidenceLink, ...]
    evidence_paths: tuple[OperationalContextEvidencePath, ...]
    stale_sources: tuple[str, ...]
    conflicts: tuple[str, ...]
    autonomy_ceiling: Autonomy

    def __post_init__(self) -> None:
        if not self.snapshot_id or not self.target_resource_id:
            raise ValueError("operational context identities MUST be non-empty")
        if self.cutoff.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("operational context timestamps MUST be timezone-aware")

    @property
    def review_required(self) -> bool:
        return self.autonomy_ceiling is Autonomy.SHADOW_ONLY
