"""Pure, bounded rendering for send-only notification emails."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from importlib.resources import files
from string import Template
from urllib.parse import urlsplit

from fdai.shared.providers.notifications.base import NotificationMessage, TrustTier

_INCIDENT_OPEN_NOTICE = "opened"
_INCIDENT_OPEN_TEMPLATE = Template(
    files("fdai.delivery.notifications")
    .joinpath("templates/incident-opened.html")
    .read_text(encoding="utf-8")
)


@dataclass(frozen=True, slots=True)
class RenderedEmailContent:
    """Provider-neutral email subject and multipart content."""

    subject: str
    plain_text: str
    html: str | None = None


def render_email_content(message: NotificationMessage) -> RenderedEmailContent:
    """Render a rich incident-open email or preserve the generic fallback."""
    if not _is_incident_open(message):
        return RenderedEmailContent(
            subject=message.title[:255],
            plain_text=message.body_markdown,
        )

    incident_id = message.metadata.get("incident_id", message.correlation_id)
    severity = message.metadata.get("incident_severity", message.severity.value).upper()
    state = message.metadata.get("incident_state", "open")
    opened_at = message.metadata.get("opened_at")
    evidence_count = message.metadata.get("member_event_count")
    assignment_state = message.metadata.get("assignment_state")
    audit_id = message.audit_id or "Unavailable"
    incident_url = _first_https_link(message)

    subject = f"[{severity}] Incident opened"
    plain_lines = [
        subject,
        "",
        f"Incident: {incident_id}",
        f"State: {state}",
        "Execution: No action is authorized by this notification.",
        f"Audit: {audit_id}",
    ]
    if opened_at is not None:
        plain_lines.insert(5, f"Opened: {opened_at}")
    if evidence_count is not None:
        plain_lines.insert(-2, f"Correlated evidence: {evidence_count}")
    if assignment_state is not None:
        plain_lines.insert(-2, f"Assignment: {assignment_state}")
    if incident_url is not None:
        plain_lines.extend(("", f"Open incident detail: {incident_url}"))

    return RenderedEmailContent(
        subject=subject[:255],
        plain_text="\n".join(plain_lines),
        html=_incident_open_html(
            severity=severity,
            state=state,
            opened_at=opened_at,
            evidence_count=evidence_count,
            assignment_state=assignment_state,
            incident_id=incident_id,
            audit_id=audit_id,
            incident_url=incident_url,
        ),
    )


def _is_incident_open(message: NotificationMessage) -> bool:
    return (
        message.category == "operational_alert"
        and message.trust_tier is TrustTier.A2_OPERATIONAL_ALERT
        and message.metadata.get("notice_kind") == _INCIDENT_OPEN_NOTICE
        and message.audit_id is not None
        and message.audit_id.startswith("incident:")
        and message.audit_id.endswith(":opened")
    )


def _first_https_link(message: NotificationMessage) -> str | None:
    for link in message.links:
        parsed = urlsplit(link.url)
        if parsed.scheme == "https" and parsed.netloc:
            return link.url
    return None


def _incident_open_html(
    *,
    severity: str,
    state: str,
    opened_at: str | None,
    evidence_count: str | None,
    assignment_state: str | None,
    incident_id: str,
    audit_id: str,
    incident_url: str | None,
) -> str:
    values = {
        "severity": escape(severity),
        "state": escape(state),
        "incident_id": escape(incident_id),
        "audit_id": escape(audit_id),
        "dateline": (
            ""
            if opened_at is None
            else '<tr><td style="padding:12px 34px;background:#f3f0e9;'
            "border-top:1px solid #e1ddd5;border-bottom:1px solid #e1ddd5;"
            "font-size:10px;color:#74716c;text-transform:uppercase;"
            f'letter-spacing:.04em">Opened {escape(opened_at)}</td></tr>'
        ),
        "evidence_row": _fact_row("Correlated evidence", evidence_count),
        "assignment_row": _fact_row("Assignment", assignment_state),
    }
    detail_link = ""
    if incident_url is not None:
        detail_link = (
            '<a href="'
            + escape(incident_url, quote=True)
            + '" style="color:#385d7a;text-decoration:none;border-bottom:1px solid #9eafbc">'
            "Open incident detail &rarr;</a>"
        )
    return _INCIDENT_OPEN_TEMPLATE.substitute(values, detail_link=detail_link)


def _fact_row(label: str, value: str | None) -> str:
    if value is None:
        return ""
    return (
        '<tr><td style="padding:11px 0;border-top:1px solid #ddd8cf;'
        f'color:#74716c;font-size:12px">{escape(label)}</td>'
        '<td align="right" style="padding:11px 0;border-top:1px solid #ddd8cf;'
        f'font-size:13px">{escape(value)}</td></tr>'
    )


__all__ = ["RenderedEmailContent", "render_email_content"]
