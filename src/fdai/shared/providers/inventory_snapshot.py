"""Atomic inventory snapshot persistence and fallback coordination contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from .inventory import InventoryBatch


class InventoryObservationKind(StrEnum):
    """Authority carried by an inventory snapshot."""

    OBSERVED = "observed"
    EXPECTED = "expected"


class InventoryFailureCode(StrEnum):
    """Bounded failure taxonomy exposed to operators and audit."""

    NETWORK_BLOCKED = "network_blocked"
    DNS_FAILED = "dns_failed"
    TOKEN_FAILED = "token_failed"  # noqa: S105 - failure code, not a credential
    FORBIDDEN = "forbidden"
    THROTTLED = "throttled"
    PARTIAL = "partial"
    SOURCE_UNAVAILABLE = "source_unavailable"
    INVALID_DATA = "invalid_data"


@dataclass(frozen=True, slots=True)
class InventoryCoverageManifest:
    """Declared source coverage for one immutable snapshot attempt."""

    source: str
    scopes: tuple[str, ...]
    resource_types: tuple[str, ...]
    observation_kind: InventoryObservationKind = InventoryObservationKind.OBSERVED
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("InventoryCoverageManifest.source MUST be non-empty")
        if not self.scopes:
            raise ValueError("InventoryCoverageManifest.scopes MUST NOT be empty")
        if not self.resource_types:
            raise ValueError("InventoryCoverageManifest.resource_types MUST NOT be empty")


@dataclass(frozen=True, slots=True)
class InventoryAttemptFailure:
    """Sanitized terminal failure for one source attempt."""

    code: InventoryFailureCode
    message: str

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("InventoryAttemptFailure.message MUST be non-empty")


@runtime_checkable
class InventorySnapshotStore(Protocol):
    """Stage immutable candidates and atomically select the active snapshot."""

    async def begin(self, manifest: InventoryCoverageManifest) -> str:
        """Create a collecting attempt and return its opaque id."""
        ...

    async def stage(self, attempt_id: str, batch: InventoryBatch) -> None:
        """Persist one non-terminal candidate batch without exposing it to readers."""
        ...

    async def promote(self, attempt_id: str, manifest: InventoryCoverageManifest) -> None:
        """Atomically make one fully validated candidate active."""
        ...

    async def fail(self, attempt_id: str, failure: InventoryAttemptFailure) -> None:
        """Record failure while retaining the last active snapshot."""
        ...


@dataclass(frozen=True, slots=True)
class InventorySource:
    """One ordered inventory source and its declared coverage."""

    name: str
    inventory: object
    manifest: InventoryCoverageManifest

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("InventorySource.name MUST be non-empty")


@dataclass(frozen=True, slots=True)
class InventorySyncResult:
    """Outcome of an ordered fallback run."""

    attempt_id: str
    source: str
    failures: tuple[InventoryAttemptFailure, ...] = ()


class InventorySourcesExhaustedError(RuntimeError):
    """No configured source produced a complete snapshot."""

    def __init__(self, failures: Sequence[InventoryAttemptFailure]) -> None:
        self.failures = tuple(failures)
        summary = ", ".join(failure.code.value for failure in self.failures)
        super().__init__(f"all inventory sources failed: {summary}")


__all__ = [
    "InventoryAttemptFailure",
    "InventoryCoverageManifest",
    "InventoryFailureCode",
    "InventoryObservationKind",
    "InventorySnapshotStore",
    "InventorySource",
    "InventorySourcesExhaustedError",
    "InventorySyncResult",
]
