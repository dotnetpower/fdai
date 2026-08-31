"""Dependency contracts for the Operator Cost Governance family."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai_service_contracts import (
    CostAccessGrant,
    CostAnalyticsProjection,
    CostDisclosureCeiling,
    CostGovernanceUnavailableReason,
    CostProjectionRecord,
)


@dataclass(frozen=True, slots=True)
class CostActivationSnapshot:
    """Persisted manager-derived activation state read without reinterpretation."""

    vertical_id: str
    package_id: str
    available: bool
    enabled: bool
    availability_reasons: tuple[str, ...]
    package_version: str
    image_digest: str
    asset_manifest_digest: str
    semantic_profile_digest: str
    ontology_release_digest: str
    revision: int

    def __post_init__(self) -> None:
        reasons = tuple(sorted(set(self.availability_reasons)))
        object.__setattr__(self, "availability_reasons", reasons)
        if len(reasons) > 32 or any(
            not reason.isascii() or not 1 <= len(reason) <= 256 for reason in reasons
        ):
            raise ValueError("availability reasons must be bounded non-empty ASCII")
        if self.available == bool(reasons):
            raise ValueError("available must match empty availability reasons")
        if self.enabled and not self.available:
            raise ValueError("unavailable Cost Governance cannot be enabled")


@dataclass(frozen=True, slots=True)
class CostAccessDecision:
    """One server-owned grant decision and deployment disclosure ceiling."""

    grant: CostAccessGrant | None
    ceiling: CostDisclosureCeiling | None
    reason: CostGovernanceUnavailableReason | None = None


class CostAccessReader(Protocol):
    """Read one user-specific grant before any activation or cost-table query."""

    async def read_access(
        self,
        *,
        principal_id: str,
        purpose: str,
        scope: str,
        now: datetime,
    ) -> CostAccessDecision: ...


class CostActivationReader(Protocol):
    """Read the authoritative package activation snapshot."""

    async def read_activation(self, package_id: str) -> CostActivationSnapshot | None: ...


class CostActivationWriter(Protocol):
    """Apply one audited, revision-fenced package enablement preference."""

    async def set_enabled(
        self,
        *,
        package_id: str,
        actor_id: str,
        enabled: bool,
        expected_revision: int,
        request_id: str,
    ) -> CostActivationSnapshot: ...


class CostProjectionReader(Protocol):
    """Read retained immutable observations only after access and activation pass."""

    async def read_records(
        self,
        *,
        surface: str,
        scope: str,
        limit: int,
    ) -> tuple[CostProjectionRecord, ...]: ...


class CostAnalyticsReader(Protocol):
    """Read the latest disclosure-safe analytics snapshot for one scope."""

    async def read_analytics(self, *, scope: str) -> CostAnalyticsProjection | None: ...


__all__ = [
    "CostAccessDecision",
    "CostAccessReader",
    "CostAnalyticsReader",
    "CostActivationReader",
    "CostActivationSnapshot",
    "CostActivationWriter",
    "CostProjectionReader",
]
