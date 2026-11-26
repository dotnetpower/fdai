"""PagerDuty Events API v2 adapter.

Endpoint: ``https://events.pagerduty.com/v2/enqueue`` (default) -
overridable so a fork can point at Opsgenie / an on-prem PagerDuty proxy.
Only the ``trigger`` action is emitted here; ``acknowledge`` / ``resolve``
are outside the router's scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import httpx

from fdai.shared.providers.notifications.base import (
    ChannelKind,
    DeliveryReceipt,
    NotificationMessage,
    Severity,
    TrustTier,
)

from ._http import post_json

_DEFAULT_EVENTS_URL: Final[str] = "https://events.pagerduty.com/v2/enqueue"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0


@dataclass(frozen=True, slots=True)
class PagerDutyEventsV2Config:
    channel_id: str
    routing_key: str
    """Integration key from the PagerDuty service; never logged."""

    trust_tiers: frozenset[TrustTier] = frozenset({TrustTier.A2_OPERATIONAL_ALERT})
    events_url: str = _DEFAULT_EVENTS_URL
    source: str = "fdai"
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS


class PagerDutyEventsV2Channel:
    """Triggers a PagerDuty incident via Events API v2."""

    channel_kind: Final = ChannelKind.PAGERDUTY

    def __init__(
        self,
        *,
        config: PagerDutyEventsV2Config,
        http_client: httpx.AsyncClient,
    ) -> None:
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if not config.routing_key:
            raise ValueError("routing_key MUST NOT be empty")
        if not config.events_url.startswith("https://"):
            # The Events API v2 endpoint is HTTPS; refusing anything else
            # keeps the routing_key from leaking over plaintext.
            raise ValueError("events_url MUST use https:// scheme")
        if TrustTier.A1_HIL_APPROVAL in config.trust_tiers:
            raise ValueError("PagerDuty MUST NOT carry A1 approvals")
        self._config: Final = config
        self._http: Final = http_client

    @property
    def channel_id(self) -> str:
        return self._config.channel_id

    @property
    def trust_tiers(self) -> frozenset[TrustTier]:
        return self._config.trust_tiers

    async def send(self, message: NotificationMessage) -> DeliveryReceipt:
        payload = {
            "routing_key": self._config.routing_key,
            "event_action": "trigger",
            "dedup_key": message.correlation_id,
            "payload": {
                "summary": message.title[:1024],
                "source": self._config.source,
                "severity": _pagerduty_severity(message.severity),
                "custom_details": {
                    "correlation_id": message.correlation_id,
                    "audit_id": message.audit_id,
                    "body_markdown": message.body_markdown,
                    "trust_tier": message.trust_tier.value,
                    **dict(message.metadata),
                },
            },
            "links": [{"href": link.url, "text": link.label} for link in message.links],
        }
        status, _ = await post_json(
            client=self._http,
            url=self._config.events_url,
            payload=payload,
            timeout_seconds=self._config.timeout_seconds,
            ok_statuses=(200, 202),
        )
        return DeliveryReceipt(
            channel_kind=ChannelKind.PAGERDUTY,
            channel_id=self._config.channel_id,
            delivered=True,
            provider_message_id=message.correlation_id,
            error=None if status < 400 else f"HTTP {status}",
        )


def _pagerduty_severity(severity: Severity) -> str:
    return {
        Severity.INFO: "info",
        Severity.WARN: "warning",
        Severity.ERROR: "error",
        Severity.CRITICAL: "critical",
    }[severity]


__all__ = ["PagerDutyEventsV2Channel", "PagerDutyEventsV2Config"]
