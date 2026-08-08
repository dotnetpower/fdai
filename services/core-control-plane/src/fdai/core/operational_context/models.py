"""Immutable operational context values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.state_evidence import LinkObservationMetadata


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
        if isinstance(self.max_age_seconds, bool) or not isinstance(self.max_age_seconds, int):
            raise ValueError("SourceFreshness.max_age_seconds MUST be an integer")
        if self.max_age_seconds < 1:
            raise ValueError("SourceFreshness.max_age_seconds MUST be >= 1")


@dataclass(frozen=True, slots=True)
class OperationalContextEvidenceLink:
    """One typed graph edge with optional canonical verification evidence."""

    link_type: str
    from_id: str
    to_id: str
    observation_metadata: LinkObservationMetadata | None = None

    def __post_init__(self) -> None:
        if not self.link_type or not self.from_id or not self.to_id:
            raise ValueError("operational context evidence link fields MUST be non-empty")


@dataclass(frozen=True, slots=True)
class OperationalContextEvidencePath:
    """One deterministic shortest path from the target to a context object."""

    object_id: str
    object_type: str
    revision: int
    effective_from: datetime | None
    effective_to: datetime | None
    provenance_refs: tuple[str, ...]
    links: tuple[OperationalContextEvidenceLink, ...]

    def __post_init__(self) -> None:
        if not self.object_id or not self.object_type:
            raise ValueError("operational context evidence path identities MUST be non-empty")
        if self.revision < 0:
            raise ValueError("operational context evidence path revision MUST be >= 0")
        for field_name, value in (
            ("effective_from", self.effective_from),
            ("effective_to", self.effective_to),
        ):
            if value is not None and value.tzinfo is None:
                raise ValueError(f"operational context {field_name} MUST be timezone-aware")
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to <= self.effective_from
        ):
            raise ValueError("operational context effective_to MUST be after effective_from")
        object.__setattr__(self, "provenance_refs", tuple(self.provenance_refs))
        object.__setattr__(self, "links", tuple(self.links))


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
    temporal_exclusions: tuple[OperationalContextEvidencePath, ...]
    stale_sources: tuple[str, ...]
    conflicts: tuple[str, ...]
    autonomy_ceiling: Autonomy
    clock_identity: str = "system-utc"

    def __post_init__(self) -> None:
        if not self.snapshot_id or not self.target_resource_id:
            raise ValueError("operational context identities MUST be non-empty")
        if self.cutoff.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("operational context timestamps MUST be timezone-aware")
        if not self.clock_identity.strip():
            raise ValueError("operational context clock_identity MUST be non-empty")

    @property
    def review_required(self) -> bool:
        return self.autonomy_ceiling is Autonomy.SHADOW_ONLY
