"""In-memory :class:`NotificationChannel` fakes for tests + local dev.

Every fake records every send call in an append-only list so a test can
assert exactly what the router dispatched. Failure injection is
first-class - a test can arm a fake to raise
:class:`ChannelDeliveryError` or return ``delivered=False`` to exercise
the router's fallback and HIL-escalation paths.

Fakes ship in the main package (not under ``tests/``) so downstream
forks can reuse them for their own routing tests without depending on
this repo's ``tests/`` tree.
"""

from .fakes import (
    FakeEmailChannel,
    FakeHilEscalationSink,
    FakePagerDutyChannel,
    FakeSlackChannel,
    FakeSmsChannel,
    FakeTeamsChannel,
    FakeWebhookChannel,
)

__all__ = [
    "FakeEmailChannel",
    "FakeHilEscalationSink",
    "FakePagerDutyChannel",
    "FakeSlackChannel",
    "FakeSmsChannel",
    "FakeTeamsChannel",
    "FakeWebhookChannel",
]
