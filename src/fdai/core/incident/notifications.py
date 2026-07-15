"""A2 channel notifications for the built-in incident lifecycle workflow."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from fdai.shared.contracts.models import IncidentSeverity, IncidentState
from fdai.shared.providers.notifications.base import (
    Link,
    NotificationMessage,
    Severity,
    TrustTier,
)

from .lifecycle import IncidentLifecycleNotice, IncidentNoticeKind

_CATEGORY = "operational_alert"
_MAX_ROSTER_ITEMS = 20


class NotificationDispatcher(Protocol):
    """Structural subset of NotificationRouter used by this adapter."""

    async def dispatch(self, message: NotificationMessage) -> object: ...


class RoutedIncidentLifecycleNotifier:
    """Render lifecycle notices and dispatch them through configured channels."""

    def __init__(
        self,
        *,
        dispatcher: NotificationDispatcher,
        incidents_url: str = "/incidents",
    ) -> None:
        self._dispatcher = dispatcher
        self._incidents_url = incidents_url

    async def notify(self, notice: IncidentLifecycleNotice) -> object:
        """Dispatch one A2 lifecycle message through the notification matrix."""
        return await self._dispatcher.dispatch(self._message(notice))

    def _message(self, notice: IncidentLifecycleNotice) -> NotificationMessage:
        if notice.kind is IncidentNoticeKind.ROSTER:
            return self._roster_message(notice)
        incident_id_value, incident_state, incident_severity = _notice_incident_fields(notice)
        incident_id = str(incident_id_value)
        severity = _notification_severity(incident_severity.value)
        if notice.kind is IncidentNoticeKind.OPENED:
            title = f"Incident opened: {incident_severity.value.upper()}"
            body = (
                f"Incident `{incident_id}` opened in `{incident_state.value}` state. "
                "Open the incident roster for its audited history."
            )
        elif notice.kind is IncidentNoticeKind.STATE_CHANGED:
            if notice.previous_state is None:
                raise ValueError("state_changed incident notice requires previous_state")
            title = f"Incident state changed: {incident_state.value}"
            body = (
                f"Incident `{incident_id}` changed from `{notice.previous_state.value}` "
                f"to `{incident_state.value}`. Open the incident roster for details."
            )
        elif notice.kind is IncidentNoticeKind.SLA_BREACH:
            title = f"Incident SLA breached: {incident_severity.value.upper()}"
            body = (
                f"Incident `{incident_id}` exceeded its `{incident_state.value}` "
                "response deadline. Open the incident roster for audited context."
            )
        elif notice.kind is IncidentNoticeKind.ASSIGNED:
            title = "Incident assignment changed"
            body = (
                f"Incident `{incident_id}` has a new assignment. "
                "Open the incident roster for audited details."
            )
        else:  # pragma: no cover - StrEnum exhaustiveness guard
            raise ValueError(f"unsupported incident notice kind: {notice.kind.value}")

        return NotificationMessage(
            category=_CATEGORY,
            trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
            correlation_id=incident_id,
            audit_id=incident_notice_audit_id(notice),
            title=title,
            body_markdown=body,
            severity=severity,
            links=(
                Link(label="View incident", url=f"{self._incidents_url}?incident={incident_id}"),
            ),
            metadata={
                "incident_id": incident_id,
                "incident_state": incident_state.value,
                "incident_severity": incident_severity.value,
                "notice_kind": notice.kind.value,
            },
        )

    def _roster_message(self, notice: IncidentLifecycleNotice) -> NotificationMessage:
        incidents = notice.roster
        visible = incidents[:_MAX_ROSTER_ITEMS]
        if visible:
            lines = [
                (
                    f"- `{incident.incident_id}`: "
                    f"{incident.severity.value.upper()}, {incident.state.value}"
                )
                for incident in visible
            ]
            omitted = len(incidents) - len(visible)
            if omitted:
                lines.append(f"- {omitted} additional incident(s) omitted; open the roster.")
            body = "Current incident roster:\n" + "\n".join(lines)
        else:
            body = "The current incident roster is empty."
        correlation_id = f"incident-roster:{notice.occurred_at.isoformat()}"
        return NotificationMessage(
            category=_CATEGORY,
            trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
            correlation_id=correlation_id,
            audit_id=incident_notice_audit_id(notice),
            title=f"Incident roster: {len(incidents)} item(s)",
            body_markdown=body,
            severity=Severity.INFO,
            links=(Link(label="View incidents", url=self._incidents_url),),
            metadata={
                "incident_count": str(len(incidents)),
                "notice_kind": notice.kind.value,
            },
        )


def _notification_severity(incident_severity: str) -> Severity:
    return {
        "sev1": Severity.CRITICAL,
        "sev2": Severity.ERROR,
        "sev3": Severity.WARN,
        "sev4": Severity.INFO,
        "sev5": Severity.INFO,
    }[incident_severity]


def incident_notice_audit_id(notice: IncidentLifecycleNotice) -> str:
    """Return a stable channel-dedup id for one lifecycle occurrence."""
    timestamp = notice.occurred_at.isoformat()
    if notice.kind is IncidentNoticeKind.ROSTER:
        return f"incident-roster:{timestamp}"
    incident_id, incident_state, _ = _notice_incident_fields(notice)
    if notice.kind is IncidentNoticeKind.OPENED:
        return f"incident:{incident_id}:opened"
    if notice.kind is IncidentNoticeKind.SLA_BREACH:
        return f"incident:{incident_id}:sla:{incident_state.value}:{timestamp}"
    if notice.kind is IncidentNoticeKind.ASSIGNED:
        return f"incident:{incident_id}:assigned:{timestamp}"
    previous = notice.previous_state
    if previous is None:
        raise ValueError("state_changed incident notice requires previous_state")
    return (
        f"incident:{incident_id}:state:{previous.value}:"
        f"{incident_state.value}:{timestamp}"
    )


def _notice_incident_fields(
    notice: IncidentLifecycleNotice,
) -> tuple[UUID, IncidentState, IncidentSeverity]:
    if notice.incident is not None:
        return (
            notice.incident.incident_id,
            notice.incident.state,
            notice.incident.severity,
        )
    if (
        notice.incident_id is None
        or notice.incident_state is None
        or notice.incident_severity is None
    ):
        raise ValueError(f"{notice.kind.value} incident notice requires incident fields")
    return notice.incident_id, notice.incident_state, notice.incident_severity


__all__ = [
    "NotificationDispatcher",
    "RoutedIncidentLifecycleNotifier",
    "incident_notice_audit_id",
]