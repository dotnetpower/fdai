"""Build stewardship-change notifications + recipients (decision B wiring).

Turns a stewardship / workflow change into a vendor-neutral
:class:`~fdai.shared.providers.notifications.base.NotificationMessage` plus the
ordered list of steward recipients to notify, ready for the notification router.
Pure: no dispatch, no I/O. The caller (a propose-change handler / composition
root) hands the message to :mod:`fdai.core.notifications.router` and the
recipient object ids to the channel adapter's mention field, and writes the
audit payload to the append-only store.

Design authority:
[`agent-stewardship-and-handover.md § 8`]
(../../../../docs/roadmap/interfaces/agent-stewardship-and-handover.md#8-workflow-change-notification-and-audit).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from fdai.core.stewardship.escalation import EscalationRecipient, stakeholders_for_change
from fdai.core.stewardship.model import StewardshipMap
from fdai.shared.providers.notifications.base import (
    NotificationMessage,
    Severity,
    TrustTier,
)

# A workflow / stewardship change is an operational notice, not an approval
# gate: it rides the A2 operational-alert lane. Reusing the existing category
# means no new matrix route is required (a fork MAY add a dedicated route).
CHANGE_CATEGORY = "operational_alert"


class StewardshipChangePhase(StrEnum):
    """Lifecycle phase of a governed stewardship change."""

    REQUESTED = "requested"
    MERGED = "merged"


@dataclass(frozen=True, slots=True)
class StewardshipChangeEvent:
    """A request to change a governed workflow / the stewardship map.

    ``artifact`` is the file being changed (``config/agent-stewardship.yaml`` or
    a ``rule-catalog/workflows/*.yaml``); ``affected_agents`` are the pantheon
    agents that change touches (computed via
    :func:`~fdai.core.stewardship.escalation.affected_agents_from_workflow` for a
    workflow file, or the agents whose stewards changed for the stewardship
    file).
    """

    actor_oid: str
    artifact: str
    affected_agents: tuple[str, ...]
    summary: str
    correlation_id: str
    phase: StewardshipChangePhase = StewardshipChangePhase.REQUESTED


def build_change_notification(
    mp: StewardshipMap, event: StewardshipChangeEvent
) -> tuple[NotificationMessage, tuple[EscalationRecipient, ...]]:
    """Build the notification + recipient list for a stewardship change.

    Recipients are the union of the affected agents' accountable + informed
    stewards plus the maintainer set (de-duplicated, accountable-first). The
    steward object ids ride in ``metadata['steward_oids']`` so the channel
    adapter can @mention them; the message itself fans out on the domain lane.
    """
    recipients = stakeholders_for_change(mp, event.affected_agents)
    steward_oids = tuple(r.id for r in recipients)
    agents_label = ", ".join(event.affected_agents) if event.affected_agents else "(none)"
    verb = "requested" if event.phase is StewardshipChangePhase.REQUESTED else "merged"
    body = (
        f"Change {verb} by {event.actor_oid} for `{event.artifact}`.\n\n"
        f"Affected agents: {agents_label}.\n\n{event.summary}"
    )
    message = NotificationMessage(
        category=CHANGE_CATEGORY,
        trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
        correlation_id=event.correlation_id,
        title=f"Stewardship change {verb}: {event.artifact}",
        body_markdown=body,
        severity=Severity.WARN,
        metadata={
            "artifact": event.artifact,
            "actor_oid": event.actor_oid,
            "affected_agents": agents_label,
            "steward_oids": ",".join(steward_oids),
        },
    )
    return message, recipients


def build_change_audit_payload(event: StewardshipChangeEvent) -> dict[str, str]:
    """Append-only audit payload for a stewardship-change request (L0 English).

    The caller writes this to the Saga audit store; it never suppresses the
    record of the underlying finding.
    """
    return {
        "event": f"stewardship_change_{event.phase.value}",
        "actor_oid": event.actor_oid,
        "artifact": event.artifact,
        "affected_agents": ",".join(event.affected_agents),
        "correlation_id": event.correlation_id,
        "recorded_at": datetime.now(UTC).isoformat(),
        "summary": event.summary,
    }


__all__ = [
    "CHANGE_CATEGORY",
    "StewardshipChangeEvent",
    "StewardshipChangePhase",
    "build_change_audit_payload",
    "build_change_notification",
]
