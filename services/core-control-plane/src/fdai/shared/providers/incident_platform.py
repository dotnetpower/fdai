"""Vendor-neutral incident platform read and write contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class ExternalIncidentStatus(StrEnum):
    TRIGGERED = "triggered"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class ExternalIncident:
    platform: str
    incident_ref: str
    title: str
    severity: str
    status: ExternalIncidentStatus
    created_at: datetime
    updated_at: datetime
    service_ref: str | None = None
    source_url: str | None = None

    def __post_init__(self) -> None:
        for name, value, limit in (
            ("platform", self.platform, 64),
            ("incident_ref", self.incident_ref, 256),
            ("title", self.title, 500),
            ("severity", self.severity, 32),
        ):
            if not value.strip() or len(value) > limit:
                raise ValueError(f"external incident {name} MUST be non-empty and bounded")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("external incident timestamps MUST include timezone")


class IncidentPlatformError(RuntimeError):
    """Normalized incident platform transport, auth, or shape failure."""


@runtime_checkable
class IncidentPlatform(Protocol):
    """Bounded incident reads and explicit lifecycle writes.

    Implementing this protocol grants no authority. Callers expose write
    methods only behind the normal typed action, risk, approval, and audit path.
    """

    async def list_active(self, *, limit: int = 100) -> Sequence[ExternalIncident]: ...

    async def acknowledge(self, incident_ref: str) -> ExternalIncident: ...

    async def resolve(self, incident_ref: str) -> ExternalIncident: ...

    async def add_note(self, incident_ref: str, note: str) -> None: ...


__all__ = [
    "ExternalIncident",
    "ExternalIncidentStatus",
    "IncidentPlatform",
    "IncidentPlatformError",
]
