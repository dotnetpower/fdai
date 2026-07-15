"""Incident lifecycle notification rendering tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fdai.core.incident.notifications import RoutedIncidentLifecycleNotifier
from fdai.core.incident.workflow import IncidentLifecycleNotice, IncidentNoticeKind
from fdai.shared.contracts.models import Incident, IncidentSeverity, IncidentState
from fdai.shared.providers.notifications.base import NotificationMessage, Severity, TrustTier


class CapturingDispatcher:
    def __init__(self) -> None:
        self.messages: list[NotificationMessage] = []

    async def dispatch(self, message: NotificationMessage) -> str:
        self.messages.append(message)
        return "delivered"


def _incident(number: int, *, state: IncidentState = IncidentState.OPEN) -> Incident:
    return Incident(
        schema_version="1.0.0",
        incident_id=UUID(f"00000000-0000-0000-0000-{number:012d}"),
        state=state,
        severity=IncidentSeverity.SEV2,
        opened_at=datetime(2026, 7, 15, tzinfo=UTC) + timedelta(minutes=number),
        correlation_keys=(f"resource:example-{number}",),
        member_event_ids=(UUID(f"00000000-0000-0000-0001-{number:012d}"),),
    )


async def test_open_notice_uses_operational_alert_without_resource_value() -> None:
    dispatcher = CapturingDispatcher()
    notifier = RoutedIncidentLifecycleNotifier(dispatcher=dispatcher)
    incident = _incident(1)

    result = await notifier.notify(
        IncidentLifecycleNotice(
            kind=IncidentNoticeKind.OPENED,
            actor_oid="Heimdall",
            occurred_at=datetime(2026, 7, 15, tzinfo=UTC),
            incident=incident,
            reason="untrusted resource details must not fan out",
        )
    )

    message = dispatcher.messages[0]
    assert result == "delivered"
    assert message.category == "operational_alert"
    assert message.trust_tier is TrustTier.A2_OPERATIONAL_ALERT
    assert message.severity is Severity.ERROR
    assert message.audit_id == f"incident:{incident.incident_id}:opened"
    assert str(incident.incident_id) in message.body_markdown
    assert "example-1" not in message.body_markdown
    assert "untrusted resource" not in message.body_markdown


async def test_transition_notice_names_previous_and_current_state() -> None:
    dispatcher = CapturingDispatcher()
    notifier = RoutedIncidentLifecycleNotifier(dispatcher=dispatcher)

    await notifier.notify(
        IncidentLifecycleNotice(
            kind=IncidentNoticeKind.STATE_CHANGED,
            actor_oid="operator@example.com",
            occurred_at=datetime(2026, 7, 15, tzinfo=UTC),
            incident=_incident(1, state=IncidentState.TRIAGING),
            previous_state=IncidentState.OPEN,
        )
    )

    assert "from `open` to `triaging`" in dispatcher.messages[0].body_markdown
    assert dispatcher.messages[0].audit_id == (
        "incident:00000000-0000-0000-0000-000000000001:"
        "state:open:triaging:2026-07-15T00:00:00+00:00"
    )


async def test_roster_notification_is_bounded_to_twenty_items() -> None:
    dispatcher = CapturingDispatcher()
    notifier = RoutedIncidentLifecycleNotifier(dispatcher=dispatcher)
    roster = tuple(_incident(number) for number in range(1, 24))

    await notifier.notify(
        IncidentLifecycleNotice(
            kind=IncidentNoticeKind.ROSTER,
            actor_oid="scheduler",
            occurred_at=datetime(2026, 7, 15, tzinfo=UTC),
            roster=roster,
        )
    )

    message = dispatcher.messages[0]
    assert message.title == "Incident roster: 23 item(s)"
    assert message.body_markdown.count("- `") == 20
    assert "3 additional incident(s) omitted" in message.body_markdown
    assert message.audit_id == "incident-roster:2026-07-15T00:00:00+00:00"


async def test_sla_breach_has_stable_deadline_identity() -> None:
    dispatcher = CapturingDispatcher()
    notifier = RoutedIncidentLifecycleNotifier(dispatcher=dispatcher)

    await notifier.notify(
        IncidentLifecycleNotice(
            kind=IncidentNoticeKind.SLA_BREACH,
            actor_oid="incident-sla-monitor",
            occurred_at=datetime(2026, 7, 15, 0, 5, tzinfo=UTC),
            incident_id=UUID("00000000-0000-0000-0000-000000000001"),
            incident_state=IncidentState.OPEN,
            incident_severity=IncidentSeverity.SEV1,
            reason="acknowledgement_deadline_exceeded",
        )
    )

    message = dispatcher.messages[0]
    assert message.severity is Severity.CRITICAL
    assert message.audit_id == (
        "incident:00000000-0000-0000-0000-000000000001:sla:open:2026-07-15T00:05:00+00:00"
    )
