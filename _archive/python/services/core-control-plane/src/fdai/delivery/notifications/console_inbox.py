"""Console web inbox channel: a bounded server record for A2 operational alerts.

The channel writes one content-minimal, no-authority record per message under
``console-inbox:`` in the tracked state store. Operator reads those records back for
authenticated Console readers. Writing a record is the channel's publication; it never claims
that a person has seen the message, and it carries no approval or execution link.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Final

from fdai_service_contracts.console_inbox import CONSOLE_INBOX_PREFIX

from fdai.shared.providers.notifications import (
    ChannelDeliveryError,
    ChannelKind,
    DeliveryReceipt,
    NotificationMessage,
    TrustTier,
)
from fdai.shared.providers.notifications.presentation import render_presentation
from fdai.shared.providers.state_store import StateStore

CONSOLE_INBOX_CHANNEL_ID: Final = "console-inbox"
CONSOLE_INBOX_RETAINED: Final = 200
CONSOLE_INBOX_TRUST_TIERS: Final = frozenset({TrustTier.A2_OPERATIONAL_ALERT})


def console_inbox_key(message: NotificationMessage) -> str:
    """Return the stable record key so a retried send never duplicates a record."""
    identity = message.audit_id or f"{message.category}\0{message.correlation_id}"
    return CONSOLE_INBOX_PREFIX + hashlib.sha256(identity.encode()).hexdigest()[:32]


class StateStoreConsoleInboxChannel:
    """Publish pre-redacted A2 messages to the Console inbox."""

    channel_kind = ChannelKind.CONSOLE
    trust_tiers = CONSOLE_INBOX_TRUST_TIERS

    def __init__(
        self,
        *,
        state_store: StateStore,
        channel_id: str = CONSOLE_INBOX_CHANNEL_ID,
        retained: int = CONSOLE_INBOX_RETAINED,
    ) -> None:
        if retained < 1:
            raise ValueError("console inbox retention MUST keep at least one record")
        self.channel_id = channel_id
        self._store = state_store
        self._retained = retained

    async def send(self, message: NotificationMessage) -> DeliveryReceipt:
        # Links are never stored, and the https-only link rule protects external channels, so a
        # local or relative Console link must not make the whole alert undeliverable.
        envelope = render_presentation(replace(message, links=()), channel_id=self.channel_id)
        key = console_inbox_key(message)
        record: dict[str, Any] = {
            "schema_version": "1.0.0",
            "inbox_id": key.removeprefix(CONSOLE_INBOX_PREFIX),
            "category": envelope.category,
            "trust_tier": envelope.trust_tier.value,
            "severity": envelope.severity.value,
            "title": envelope.title,
            "body": envelope.body_markdown,
            "correlation_id": envelope.correlation_id,
            "audit_id": envelope.audit_id,
            "recorded_at": datetime.now(UTC).isoformat(),
            "execution_authority": False,
        }
        try:
            await self._store.write_state_if_absent(key, record)
            await self._store.delete_states_beyond(
                CONSOLE_INBOX_PREFIX, retain_newest=self._retained
            )
        except Exception as exc:  # noqa: BLE001 - a store fault is a retryable channel fault
            raise ChannelDeliveryError("console inbox record could not be written") from exc
        return DeliveryReceipt(
            channel_kind=self.channel_kind,
            channel_id=self.channel_id,
            delivered=True,
            provider_message_id=record["inbox_id"],
        )


__all__ = [
    "CONSOLE_INBOX_CHANNEL_ID",
    "CONSOLE_INBOX_PREFIX",
    "CONSOLE_INBOX_RETAINED",
    "CONSOLE_INBOX_TRUST_TIERS",
    "StateStoreConsoleInboxChannel",
    "console_inbox_key",
]
