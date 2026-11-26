"""In-memory notification-channel fakes.

Each fake:

- records every :class:`NotificationMessage` handed to it (append-only),
- honours failure injection via ``fail_next_n`` / ``deliver_result`` /
  ``raise_next_n``,
- returns a :class:`DeliveryReceipt` with a monotonic
  ``provider_message_id``.

Deliberately six concrete classes (one per channel kind) so a test can
build a heterogenous registry - same as production - and prove the
router picks the right adapter.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import count
from typing import ClassVar

from fdai.shared.providers.notifications.base import (
    ChannelDeliveryError,
    ChannelKind,
    DeliveryReceipt,
    NotificationMessage,
    TrustTier,
)


@dataclass
class _RecordingChannel:
    """Shared behaviour for the six per-kind fakes.

    Not exported directly - the six subclasses each fix a
    :class:`ChannelKind` and inherit ``send`` / the recorder.
    """

    channel_kind: ClassVar[ChannelKind]

    channel_id: str
    trust_tiers: frozenset[TrustTier] = field(default_factory=frozenset)

    _records: list[NotificationMessage] = field(default_factory=list, init=False, repr=False)
    _fail_remaining: int = field(default=0, init=False, repr=False)
    _raise_remaining: int = field(default=0, init=False, repr=False)
    _raise_message: str = field(default="channel fake configured to raise", init=False, repr=False)
    _counter: count[int] = field(default_factory=lambda: count(1), init=False, repr=False)

    def arm_delivery_failures(self, n: int) -> None:
        """Return ``delivered=False`` for the next ``n`` sends."""
        if n < 0:
            raise ValueError("n MUST be >= 0")
        self._fail_remaining = n

    def arm_raises(self, n: int, *, message: str | None = None) -> None:
        """Raise :class:`ChannelDeliveryError` for the next ``n`` sends."""
        if n < 0:
            raise ValueError("n MUST be >= 0")
        self._raise_remaining = n
        if message is not None:
            self._raise_message = message

    async def send(self, message: NotificationMessage) -> DeliveryReceipt:
        # Record BEFORE we inject the failure so a test can prove the
        # message reached the adapter even when it errors.
        self._records.append(message)

        if self._raise_remaining > 0:
            self._raise_remaining -= 1
            raise ChannelDeliveryError(self._raise_message)

        if self._fail_remaining > 0:
            self._fail_remaining -= 1
            return DeliveryReceipt(
                channel_kind=self.channel_kind,
                channel_id=self.channel_id,
                delivered=False,
                provider_message_id=None,
                error="fake: soft delivery failure",
            )

        return DeliveryReceipt(
            channel_kind=self.channel_kind,
            channel_id=self.channel_id,
            delivered=True,
            provider_message_id=f"{self.channel_kind.value}-{next(self._counter)}",
        )

    @property
    def records(self) -> tuple[NotificationMessage, ...]:
        return tuple(self._records)


class FakeTeamsChannel(_RecordingChannel):
    """In-memory :class:`~fdai.shared.providers.notifications.TeamsChannel`."""

    channel_kind: ClassVar[ChannelKind] = ChannelKind.TEAMS


class FakeSlackChannel(_RecordingChannel):
    """In-memory :class:`~fdai.shared.providers.notifications.SlackChannel`."""

    channel_kind: ClassVar[ChannelKind] = ChannelKind.SLACK


class FakeEmailChannel(_RecordingChannel):
    """In-memory :class:`~fdai.shared.providers.notifications.EmailChannel`."""

    channel_kind: ClassVar[ChannelKind] = ChannelKind.EMAIL


class FakeWebhookChannel(_RecordingChannel):
    """In-memory :class:`~fdai.shared.providers.notifications.WebhookChannel`."""

    channel_kind: ClassVar[ChannelKind] = ChannelKind.WEBHOOK


class FakePagerDutyChannel(_RecordingChannel):
    """In-memory :class:`~fdai.shared.providers.notifications.PagerDutyChannel`."""

    channel_kind: ClassVar[ChannelKind] = ChannelKind.PAGERDUTY


class FakeSmsChannel(_RecordingChannel):
    """In-memory :class:`~fdai.shared.providers.notifications.SmsChannel`."""

    channel_kind: ClassVar[ChannelKind] = ChannelKind.SMS


@dataclass
class FakeHilEscalationSink:
    """In-memory :class:`~fdai.shared.providers.notifications.HilEscalationSink`.

    Records every escalation so tests can assert the router fell through
    when every configured channel failed.
    """

    _entries: list[tuple[NotificationMessage, str]] = field(
        default_factory=list, init=False, repr=False
    )

    async def escalate(self, message: NotificationMessage, reason: str) -> None:
        self._entries.append((message, reason))

    @property
    def entries(self) -> Iterable[tuple[NotificationMessage, str]]:
        return tuple(self._entries)


__all__ = [
    "FakeEmailChannel",
    "FakeHilEscalationSink",
    "FakePagerDutyChannel",
    "FakeSlackChannel",
    "FakeSmsChannel",
    "FakeTeamsChannel",
    "FakeWebhookChannel",
]
