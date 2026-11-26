"""Shadow-mode notification channel: render, bound-and-record - no network.

A binding whose :class:`~fdai.shared.providers.notifications.capability.\
ChannelCapabilityState.mode` is
:attr:`~fdai.shared.providers.notifications.capability.ChannelMode.SHADOW`
is wrapped in :class:`ShadowNotificationChannel` at the composition root
instead of the vendor adapter. It satisfies
:class:`~fdai.shared.providers.notifications.NotificationChannel` structurally,
so :class:`~fdai.core.notifications.router.NotificationRouter` dispatches
through it exactly like a live adapter, but ``send`` never performs a
network call.

``send`` renders the bounded, pre-redacted presentation envelope
(:func:`fdai.shared.providers.notifications.presentation.render_presentation`)
and durably records it through an injected :class:`ShadowDeliveryRecorder`,
matching constitution principle 7 ("New capabilities start in shadow mode -
judge and log only, no execution").

``delivered=True`` on the returned receipt reflects that this channel's
complete contractual obligation - render plus durable local record - is
already finished with no unconfirmed external promise outstanding; there is
no provider acknowledgement to await because no request ever left the
process. A presentation rejection propagates as
:class:`~fdai.shared.providers.notifications.presentation.PresentationRejectedError`
(a :class:`~fdai.shared.providers.notifications.ChannelDeliveryError`
subclass), so the router treats it exactly like any other failed send and
proceeds to fallback or bounded retry.

``ShadowDeliveryRecord.record_id`` is derived deterministically from
``channel_id`` plus the message's ``correlation_id``, ``audit_id``, and
``category`` - never from a random value - so a re-issued ``send`` for the
same logical delivery always reproduces the same id. This satisfies the
pre-existing contract in `channels-and-notifications.md § 5`
("Adapters MUST implement idempotent `send`: a re-issued send with the same
`correlation_id + audit_id + category` MUST NOT create a duplicate post"):
:class:`InMemoryShadowDeliveryRecorder` treats a repeated ``record_id`` as a
no-op, and a durable production recorder MUST do the same (e.g. an upsert
keyed on ``record_id``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from fdai.shared.providers.notifications.base import (
    ChannelKind,
    DeliveryReceipt,
    NotificationMessage,
    TrustTier,
    require_channel_id,
)
from fdai.shared.providers.notifications.presentation import (
    NotificationPayloadRenderer,
    NotificationPresentationEnvelope,
    PresentationLimits,
    PresentationRejectedError,
    RenderedNotificationPayload,
    render_presentation,
)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _record_id(channel_id: str, message: NotificationMessage) -> str:
    """Deterministic idempotency key for one shadow render + record.

    Built from the same ``correlation_id + audit_id + category`` tuple that
    `channels-and-notifications.md § 5` names as an adapter's idempotency
    identity, scoped per ``channel_id`` so a fan-out to several channels for
    one message never collides. ``\\x1f`` (unit separator) delimits fields so
    no combination of field values can produce the same material as another.
    """
    material = "\x1f".join(
        (channel_id, message.correlation_id, message.audit_id or "", message.category)
    ).encode()
    return f"shadow:{hashlib.sha256(material).hexdigest()}"


@dataclass(frozen=True, slots=True)
class ShadowDeliveryRecord:
    """One durable local record of a shadow-mode render.

    Separate from the router's own per-dispatch audit entry: this is the
    shadow channel's evidence trail, not a second audit write for the same
    dispatch call.
    """

    record_id: str
    channel_id: str
    category: str
    trust_tier: TrustTier
    correlation_id: str
    envelope: NotificationPresentationEnvelope
    recorded_at: datetime
    audit_id: str | None = None
    rendered_payload: RenderedNotificationPayload | None = None


class ShadowDeliveryConflictError(RuntimeError):
    """Raised when one stable shadow id is reused for different content."""


@runtime_checkable
class ShadowDeliveryRecorder(Protocol):
    """Sink for :class:`ShadowDeliveryRecord` entries.

    A repeated :meth:`record` call carrying the same
    :attr:`ShadowDeliveryRecord.record_id` MUST be a no-op rather than a
    second append - :attr:`record_id` is a deterministic idempotency key
    (see :func:`_record_id`), so a durable implementation satisfies this
    with an upsert / insert-or-ignore keyed on ``record_id``.
    """

    async def record(self, entry: ShadowDeliveryRecord) -> None: ...


class InMemoryShadowDeliveryRecorder:
    """Local-development / test recorder. Not a durable production store.

    Keeps first-write-wins semantics keyed on ``record_id`` so a repeated
    :meth:`record` call for the same logical delivery - the re-issued-send
    case `channels-and-notifications.md § 5` requires every adapter to
    handle without a duplicate post - never grows the recorded entries.
    """

    def __init__(self) -> None:
        self._entries: dict[str, ShadowDeliveryRecord] = {}

    async def record(self, entry: ShadowDeliveryRecord) -> None:
        existing = self._entries.get(entry.record_id)
        if existing is None:
            self._entries[entry.record_id] = entry
            return
        if not _same_shadow_content(existing, entry):
            raise ShadowDeliveryConflictError(
                "shadow delivery id already exists with different bounded content"
            )

    @property
    def entries(self) -> tuple[ShadowDeliveryRecord, ...]:
        return tuple(self._entries.values())


def _same_shadow_content(left: ShadowDeliveryRecord, right: ShadowDeliveryRecord) -> bool:
    return (
        left.record_id == right.record_id
        and left.channel_id == right.channel_id
        and left.category == right.category
        and left.trust_tier is right.trust_tier
        and left.correlation_id == right.correlation_id
        and left.envelope == right.envelope
        and left.audit_id == right.audit_id
        and left.rendered_payload == right.rendered_payload
    )


@dataclass(frozen=True, slots=True)
class ShadowNotificationChannel:
    """A :class:`~fdai.shared.providers.notifications.NotificationChannel`
    that renders and records - and never sends.

    Composition registers this instead of a vendor adapter for any binding
    still in
    :attr:`~fdai.shared.providers.notifications.capability.ChannelMode.SHADOW`.
    ``channel_kind`` MUST match the vendor the binding will eventually be
    promoted to, so channel-id naming conventions stay meaningful across the
    shadow-to-enforce transition.
    """

    channel_kind: ChannelKind
    channel_id: str
    trust_tiers: frozenset[TrustTier]
    recorder: ShadowDeliveryRecorder
    payload_renderer: NotificationPayloadRenderer | None = None
    limits: PresentationLimits = field(default_factory=PresentationLimits)
    max_rendered_payload_bytes: int = 64 * 1024
    clock: Callable[[], datetime] = field(default=_utc_now)

    def __post_init__(self) -> None:
        require_channel_id(self.channel_id)
        if self.max_rendered_payload_bytes < 1:
            raise ValueError("shadow rendered payload limit MUST be positive")

    async def send(self, message: NotificationMessage) -> DeliveryReceipt:
        """Render, bound, and durably record ``message`` - no network I/O.

        Raises
        :class:`~fdai.shared.providers.notifications.presentation.PresentationRejectedError`
        (fail closed) before any recording when ``message`` carries
        secret-like content, exceeds a bounded limit, or declares unsupported
        interactive content. Raises :class:`ValueError` if the injected
        :attr:`clock` returns a naive (timezone-less) timestamp - the
        recorded evidence trail MUST stay comparable with every other
        timezone-aware timestamp this service records.
        """
        envelope = render_presentation(message, channel_id=self.channel_id, limits=self.limits)
        rendered_payload = (
            self.payload_renderer(envelope) if self.payload_renderer is not None else None
        )
        if (
            rendered_payload is not None
            and len(rendered_payload.body) > self.max_rendered_payload_bytes
        ):
            raise PresentationRejectedError(
                "rendered provider payload exceeds the shadow record limit"
            )
        recorded_at = self.clock()
        if recorded_at.tzinfo is None:
            raise ValueError("shadow delivery clock MUST return a timezone-aware datetime")
        record_id = _record_id(self.channel_id, message)
        await self.recorder.record(
            ShadowDeliveryRecord(
                record_id=record_id,
                channel_id=self.channel_id,
                category=message.category,
                trust_tier=message.trust_tier,
                correlation_id=message.correlation_id,
                envelope=envelope,
                recorded_at=recorded_at,
                audit_id=message.audit_id,
                rendered_payload=rendered_payload,
            )
        )
        return DeliveryReceipt(
            channel_kind=self.channel_kind,
            channel_id=self.channel_id,
            delivered=True,
            provider_message_id=record_id,
        )


__all__ = [
    "InMemoryShadowDeliveryRecorder",
    "ShadowDeliveryConflictError",
    "ShadowDeliveryRecord",
    "ShadowDeliveryRecorder",
    "ShadowNotificationChannel",
]
