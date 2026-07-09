"""Router per-channel localization tests (Option C, step 3).

A message carrying a ``template_key`` is rendered into the destination channel's
locale before ``send``; a message without one is passed through unchanged. The
audit entry always uses the original (English) message, so the L0 record stays
intact. No Hangul literals here (english-only gate) - ko is asserted
structurally.
"""

from __future__ import annotations

from typing import Any

import pytest

from fdai.core.notifications import (
    ChannelRegistry,
    NotificationRouter,
    load_matrix_from_mapping,
)
from fdai.shared.providers.notifications import NotificationMessage, TrustTier
from fdai.shared.providers.testing.notifications import (
    FakeHilEscalationSink,
    FakeTeamsChannel,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_EN_TITLE = "FDAI decision: auto (compute.vm)"
_PARAMS = {
    "decision": "auto",
    "resource_title": "compute.vm",
    "resource_body": "compute.vm",
    "rules": "nsg-deny-all",
    "mode": "shadow",
}


def _router(channel: FakeTeamsChannel, channels_cfg: Any = None) -> NotificationRouter:
    matrix = load_matrix_from_mapping(
        {
            "matrix": {
                "version": 1,
                "default_route": "operational_alert",
                "routes": {
                    "operational_alert": {
                        "trust_tier": TrustTier.A2_OPERATIONAL_ALERT.value,
                        "primary": "teams-ops-prd",
                    },
                },
                **({"channels": channels_cfg} if channels_cfg else {}),
            }
        }
    )
    registry = ChannelRegistry(channels={channel.channel_id: channel})
    return NotificationRouter(
        matrix=matrix,
        registry=registry,
        audit_store=InMemoryStateStore(),
        hil_sink=FakeHilEscalationSink(),
    )


def _message(*, template_key: str | None) -> NotificationMessage:
    return NotificationMessage(
        category="operational_alert",
        trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
        correlation_id="cid-1",
        title=_EN_TITLE,
        body_markdown="**Decision:** auto",
        template_key=template_key,
        params=_PARAMS if template_key else {},
    )


def _channel() -> FakeTeamsChannel:
    return FakeTeamsChannel(
        channel_id="teams-ops-prd",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
    )


@pytest.mark.asyncio
async def test_ko_channel_receives_localized_copy() -> None:
    channel = _channel()
    router = _router(channel, {"teams-ops-prd": {"locale": "ko"}})
    message = _message(template_key="decision")

    await router.dispatch(message)

    received = channel.records[0]
    # Localized: differs from the English baked title, but keeps L0 values + mark.
    assert received.title != _EN_TITLE
    assert "auto" in received.title
    assert "FDAI" in received.title
    assert "decision:" not in received.title
    # The original message (audited) is untouched - L0 stays English.
    assert message.title == _EN_TITLE


@pytest.mark.asyncio
async def test_en_channel_is_byte_identical() -> None:
    channel = _channel()
    router = _router(channel)  # no channels cfg -> default en
    await router.dispatch(_message(template_key="decision"))
    assert channel.records[0].title == _EN_TITLE


@pytest.mark.asyncio
async def test_message_without_template_key_is_passed_through() -> None:
    channel = _channel()
    router = _router(channel, {"teams-ops-prd": {"locale": "ko"}})
    await router.dispatch(_message(template_key=None))
    # No template_key -> sent as-is even on a ko channel.
    assert channel.records[0].title == _EN_TITLE
