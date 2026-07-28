"""Read-only previews of production notification templates."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.delivery.notifications.email_rendering import render_email_content
from fdai.shared.providers.notifications.base import (
    Link,
    NotificationMessage,
    Severity,
    TrustTier,
)

ROUTE_PATH = "/notification-templates/incident-opened"
_PLACEHOLDER_INCIDENT_ID = "00000000-0000-0000-0000-000000000000"


def make_notification_template_route(
    *,
    authorize: Callable[[Request], Awaitable[str]],
) -> Route:
    """Build the authenticated incident-open template preview route."""

    async def get_incident_opened_template(request: Request) -> Response:
        await authorize(request)
        content = render_email_content(_preview_message())
        if content.html is None:  # pragma: no cover - fixed preview contract guard
            raise RuntimeError("incident-open template renderer returned no HTML")
        return JSONResponse(
            {
                "key": "incident-opened",
                "subject": content.subject,
                "plain_text": content.plain_text,
                "html": content.html,
            }
        )

    return Route(ROUTE_PATH, get_incident_opened_template, methods=["GET"])


def _preview_message() -> NotificationMessage:
    return NotificationMessage(
        category="operational_alert",
        trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
        correlation_id=_PLACEHOLDER_INCIDENT_ID,
        audit_id=f"incident:{_PLACEHOLDER_INCIDENT_ID}:opened",
        title="Incident opened: SEV2",
        body_markdown="Synthetic incident-open template preview.",
        severity=Severity.ERROR,
        links=(
            Link(
                label="View incident",
                url=(f"https://example.com/incidents?incident={_PLACEHOLDER_INCIDENT_ID}"),
            ),
        ),
        metadata={
            "notice_kind": "opened",
            "incident_id": _PLACEHOLDER_INCIDENT_ID,
            "incident_state": "open",
            "incident_severity": "sev2",
            "opened_at": "2026-07-15T06:03:00+00:00",
            "member_event_count": "8",
            "assignment_state": "Unassigned",
        },
    )


__all__ = ["ROUTE_PATH", "make_notification_template_route"]
