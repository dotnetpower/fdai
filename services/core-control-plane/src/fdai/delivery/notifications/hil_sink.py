"""StateStore-backed HilEscalationSink - the router's fail-safe queue.

When :class:`~fdai.core.notifications.router.NotificationRouter` exhausts
every channel for a route (primary + all fallbacks failed), it calls the
sink so the message is never silently dropped ("fail toward safety").
This implementation parks the escalation in the :class:`StateStore` and
appends one audit entry.

Tenant-agnostic: it carries only the already-redacted
:class:`NotificationMessage` fields - no secrets, no customer values. A
fork MAY bind a different queue backend (its own ticketing system) by
implementing the :class:`HilEscalationSink` Protocol; this StateStore
version is the reusable upstream default.

Lives under ``delivery/`` so ``core/`` cannot import it (the router
depends only on the ``HilEscalationSink`` Protocol).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from fdai.shared.providers.notifications.base import NotificationMessage
from fdai.shared.providers.state_store import StateStore

_ESCALATION_PREFIX: Final = "notify_escalation:"
_DEFAULT_ACTOR: Final = "fdai.notifications.hil_sink"


class StateStoreHilEscalationSink:
    """Persist a router escalation into the StateStore + audit trail.

    Implements the :class:`HilEscalationSink` Protocol. Idempotent by
    ``(category, correlation_id)``: re-escalating the same message
    replaces the parked record rather than duplicating it, so an
    at-least-once retry cannot double-queue.
    """

    def __init__(self, *, state_store: StateStore, actor: str = _DEFAULT_ACTOR) -> None:
        self._state_store = state_store
        self._actor = actor

    async def escalate(self, message: NotificationMessage, reason: str) -> None:
        now = datetime.now(UTC).isoformat()
        key = f"{_ESCALATION_PREFIX}{message.category}:{message.correlation_id}"
        record = {
            "category": message.category,
            "trust_tier": str(message.trust_tier),
            "correlation_id": message.correlation_id,
            "title": message.title,
            "severity": str(message.severity),
            "reason": reason,
            "escalated_at": now,
            "audit_id": message.audit_id,
        }
        await self._state_store.write_state(key, record)
        await self._state_store.append_audit_entry(
            {
                "kind": "notification.escalation",
                "actor": self._actor,
                "category": message.category,
                "trust_tier": str(message.trust_tier),
                "correlation_id": message.correlation_id,
                "severity": str(message.severity),
                "reason": reason,
                "timestamp": now,
            }
        )
