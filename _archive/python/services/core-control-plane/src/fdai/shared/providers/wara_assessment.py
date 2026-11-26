"""Provider-neutral read-only observation seam for WARA assessment."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


class WaraObservationError(RuntimeError):
    """A bounded WARA observation could not be completed."""


@dataclass(frozen=True, slots=True)
class WaraReadPlan:
    recommendation_id: str
    query_digest: str
    evaluator_ref: str
    evaluator_bindings_digest: str
    workload_id: str
    resource_ids: tuple[str, ...]
    provider_resource_types: tuple[str, ...]
    inventory_generation: str
    maximum_rows: int
    timeout_seconds: int
    evidence_freshness_ceiling_seconds: int

    def __post_init__(self) -> None:
        if not self.recommendation_id or not self.workload_id or not self.evaluator_ref:
            raise ValueError("WARA read plan requires recommendation, workload, and evaluator ids")
        if re.fullmatch(r"sha256:[a-f0-9]{64}", self.query_digest) is None:
            raise ValueError("WARA read plan query digest MUST be lowercase SHA-256")
        if re.fullmatch(r"sha256:[a-f0-9]{64}", self.evaluator_bindings_digest) is None:
            raise ValueError("WARA read plan evaluator binding digest MUST be lowercase SHA-256")
        if not self.resource_ids or self.resource_ids != tuple(sorted(set(self.resource_ids))):
            raise ValueError("WARA read plan resource_ids MUST be non-empty, unique, and ordered")
        if len(self.resource_ids) > 200 or any(len(item) > 2048 for item in self.resource_ids):
            raise ValueError("WARA read plan resource_ids exceed the scope bound")
        if (
            not self.provider_resource_types
            or len(self.provider_resource_types) > 32
            or self.provider_resource_types != tuple(sorted(set(self.provider_resource_types)))
        ):
            raise ValueError(
                "WARA read plan provider resource types MUST be non-empty, unique, and ordered"
            )
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
    evaluator_ref: str
    evaluator_bindings_digest: str
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
