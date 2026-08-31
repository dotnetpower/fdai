"""Provider-neutral read-only observation seam for WARA assessment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


class WaraObservationError(RuntimeError):
    """A bounded WARA observation could not be completed."""


@dataclass(frozen=True, slots=True)
class WaraReadPlan:
    recommendation_id: str
    query_digest: str
    workload_id: str
    resource_ids: tuple[str, ...]
    provider_resource_types: tuple[str, ...]
    inventory_generation: str
    maximum_rows: int
    timeout_seconds: int
    evidence_freshness_ceiling_seconds: int

    def __post_init__(self) -> None:
        if not self.recommendation_id or not self.workload_id:
            raise ValueError("WARA read plan requires recommendation and workload ids")
        if not self.resource_ids or self.resource_ids != tuple(sorted(set(self.resource_ids))):
            raise ValueError("WARA read plan resource_ids MUST be non-empty, unique, and ordered")
        if not self.provider_resource_types:
            raise ValueError("WARA read plan requires provider resource types")
        if self.maximum_rows < 1 or self.maximum_rows > 1000:
            raise ValueError("WARA read plan maximum_rows MUST be between 1 and 1000")
        if self.timeout_seconds < 1 or self.timeout_seconds > 60:
            raise ValueError("WARA read plan timeout_seconds MUST be between 1 and 60")
        if self.evidence_freshness_ceiling_seconds < 60:
            raise ValueError(
                "WARA read plan evidence freshness ceiling MUST be at least 60 seconds"
            )


@dataclass(frozen=True, slots=True)
class WaraObservationReceipt:
    recommendation_id: str
    query_digest: str
    workload_id: str
    resource_ids: tuple[str, ...]
    inventory_generation: str
    observed_at: datetime
    recorded_at: datetime
    evidence_digest: str
    complete: bool
    truncated: bool
    conflicting: bool
    synthetic: bool
    satisfied: bool | None


@runtime_checkable
class WaraAssessmentObservationProvider(Protocol):
    """Execute an admitted bounded read plan without returning policy authority."""

    async def observe(self, plan: WaraReadPlan) -> WaraObservationReceipt:
        """Return one observation receipt or raise WaraObservationError."""
        ...


__all__ = [
    "WaraAssessmentObservationProvider",
    "WaraObservationError",
    "WaraObservationReceipt",
    "WaraReadPlan",
]
