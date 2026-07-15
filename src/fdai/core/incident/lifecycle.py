"""Types and seams for the built-in incident lifecycle workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from fdai.shared.contracts.models import Incident, IncidentSeverity, IncidentState


class IncidentWorkflowError(RuntimeError):
    """Base error for rejected built-in incident workflow requests."""


class IncidentWorkflowForbiddenError(IncidentWorkflowError, PermissionError):
    """Raised when an operator or agent cannot use the workflow."""


class IncidentConfirmationError(IncidentWorkflowError):
    """Raised when a chat proposal is stale, mismatched, or not confirmed."""


class IncidentNoticeKind(StrEnum):
    """Lifecycle events emitted through the workflow's notification seam."""

    OPENED = "opened"
    STATE_CHANGED = "state_changed"
    ROSTER = "roster"
    SLA_BREACH = "sla_breach"
    ASSIGNED = "assigned"


@dataclass(frozen=True, slots=True)
class IncidentLifecycleNotice:
    """Typed notification input emitted after an audited lifecycle write."""

    kind: IncidentNoticeKind
    actor_oid: str
    occurred_at: datetime
    incident: Incident | None = None
    incident_id: UUID | None = None
    incident_state: IncidentState | None = None
    incident_severity: IncidentSeverity | None = None
    previous_state: IncidentState | None = None
    reason: str | None = None
    roster: tuple[Incident, ...] = ()


@runtime_checkable
class IncidentLifecycleNotifier(Protocol):
    """Deliver one incident lifecycle or roster notification."""

    async def notify(self, notice: IncidentLifecycleNotice) -> object | None: ...


class IncidentOperatorPrincipal(Protocol):
    """Structural operator identity accepted from conversation or API adapters."""

    @property
    def id(self) -> str: ...

    @property
    def role(self) -> object: ...


class NullIncidentLifecycleNotifier:
    """No-op notifier used when channels have not been composed."""

    async def notify(self, notice: IncidentLifecycleNotice) -> None:  # noqa: ARG002
        return None


@dataclass(frozen=True, slots=True)
class IncidentWorkflowResult:
    """Created or transitioned incident plus its notification result."""

    incident: Incident
    response: str
    notification_result: object | None
    created: bool = False
    changed: bool = False


@dataclass(frozen=True, slots=True)
class IncidentNotificationDeferred:
    """A lifecycle write succeeded but notification awaits durable replay."""

    error_type: str


@dataclass(frozen=True, slots=True)
class IncidentRosterResult:
    """Stable incident roster plus the optional notification result."""

    incidents: tuple[Incident, ...]
    notification_result: object | None = None


@dataclass(frozen=True, slots=True)
class IncidentTicketLink:
    """Audited external ticket associated with an incident."""

    incident_id: UUID
    provider: str
    ticket_id: str
    ticket_url: str | None
    linked_at: datetime
    linked_by: str


__all__ = [
    "IncidentConfirmationError",
    "IncidentLifecycleNotice",
    "IncidentLifecycleNotifier",
    "IncidentNotificationDeferred",
    "IncidentNoticeKind",
    "IncidentOperatorPrincipal",
    "IncidentRosterResult",
    "IncidentTicketLink",
    "IncidentWorkflowError",
    "IncidentWorkflowForbiddenError",
    "IncidentWorkflowResult",
    "NullIncidentLifecycleNotifier",
]
