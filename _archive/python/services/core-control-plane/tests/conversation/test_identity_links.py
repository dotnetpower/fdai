"""Explicit cross-channel identity link safety tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.conversation import (
    ChannelSenderKey,
    CrossChannelIdentityLinkError,
    CrossChannelIdentityLinkService,
    InMemoryChannelPairingStore,
    InMemoryCrossChannelIdentityLinkStore,
    PairingRequest,
)
from fdai.shared.providers.conversation_channel import ConversationChannelKind

_NOW = datetime(2026, 7, 17, 6, 0, tzinfo=UTC)
_SLACK = ChannelSenderKey(ConversationChannelKind.SLACK, "slack-channel", "slack-user")
_TEAMS = ChannelSenderKey(ConversationChannelKind.TEAMS, "teams-channel", "teams-user")


class _Authorizer:
    def can_approve_pairing(self, actor_id: str) -> bool:
        # Case-insensitive, like a directory-group lookup: the core must hold
        # its distinct-approver rule whatever an authorizer implementation does.
        return actor_id.strip().casefold() == "owner-example"


async def _pair(
    store: InMemoryChannelPairingStore,
    sender: ChannelSenderKey,
    principal_id: str,
) -> None:
    await store.create_pending(
        PairingRequest(
            sender=sender,
            code_digest="a" * 64,
            created_at=_NOW,
            expires_at=_NOW + timedelta(hours=1),
        ),
        max_pending=3,
    )
    approved = await store.approve_pending(
        sender,
        code_digest="a" * 64,
        principal_id=principal_id,
        at=_NOW,
    )
    assert approved is not None


async def test_independently_approved_senders_link_idempotently() -> None:
    pairings = InMemoryChannelPairingStore()
    links = InMemoryCrossChannelIdentityLinkStore()
    await _pair(pairings, _SLACK, "operator-example")
    await _pair(pairings, _TEAMS, "operator-example")
    service = CrossChannelIdentityLinkService(
        pairings=pairings,
        links=links,
        authorizer=_Authorizer(),
    )

    first = await service.link(
        _SLACK,
        _TEAMS,
        principal_id="operator-example",
        actor_id="owner-example",
        at=_NOW,
    )
    repeated = await service.link(
        _TEAMS,
        _SLACK,
        principal_id="operator-example",
        actor_id="owner-example",
        at=_NOW,
    )

    assert first == repeated
    assert len(await links.list_for_principal("operator-example")) == 1


async def test_distinct_principals_cannot_be_merged() -> None:
    pairings = InMemoryChannelPairingStore()
    links = InMemoryCrossChannelIdentityLinkStore()
    await _pair(pairings, _SLACK, "operator-one")
    await _pair(pairings, _TEAMS, "operator-two")
    service = CrossChannelIdentityLinkService(
        pairings=pairings,
        links=links,
        authorizer=_Authorizer(),
    )

    with pytest.raises(CrossChannelIdentityLinkError, match="cannot merge"):
        await service.link(
            _SLACK,
            _TEAMS,
            principal_id="operator-one",
            actor_id="owner-example",
            at=_NOW,
        )

    assert await links.list_for_principal("operator-one") == ()


async def test_unapproved_same_channel_or_self_approved_links_are_denied() -> None:
    pairings = InMemoryChannelPairingStore()
    links = InMemoryCrossChannelIdentityLinkStore()
    await _pair(pairings, _SLACK, "operator-example")
    service = CrossChannelIdentityLinkService(
        pairings=pairings,
        links=links,
        authorizer=_Authorizer(),
    )
    with pytest.raises(CrossChannelIdentityLinkError, match="independently approved"):
        await service.link(
            _SLACK,
            _TEAMS,
            principal_id="operator-example",
            actor_id="owner-example",
            at=_NOW,
        )
    with pytest.raises(CrossChannelIdentityLinkError, match="cross channel"):
        await service.link(
            _SLACK,
            ChannelSenderKey(ConversationChannelKind.SLACK, "other", "other"),
            principal_id="operator-example",
            actor_id="owner-example",
            at=_NOW,
        )
    with pytest.raises(CrossChannelIdentityLinkError, match="distinct approver"):
        await service.link(
            _SLACK,
            _TEAMS,
            principal_id="owner-example",
            actor_id="owner-example",
            at=_NOW,
        )
    # An identity string is the same principal however it is cased, so the
    # distinct-approver requirement must not be satisfied by recasing.
    with pytest.raises(CrossChannelIdentityLinkError, match="distinct approver"):
        await service.link(
            _SLACK,
            _TEAMS,
            principal_id="owner-example",
            actor_id="OWNER-EXAMPLE",
            at=_NOW,
        )
