"""Channel sender pairing and allowlist tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.conversation.channel_access import (
    ChannelAccessError,
    ChannelAccessMode,
    ChannelAccessService,
    ChannelSenderKey,
    InMemoryChannelPairingStore,
)
from fdai.core.conversation.session import Principal, Role
from fdai.shared.providers.conversation_channel import ConversationChannelKind, InboundTurn
from fdai.shared.telemetry import InMemoryRoutingTransitionSink

_NOW = datetime(2026, 7, 17, 5, 0, tzinfo=UTC)


class _Identities:
    def __init__(self) -> None:
        self.principals = {"operator-1": Principal(id="operator-1", role=Role.READER)}

    async def principal_for_id(self, principal_id: str) -> Principal | None:
        return self.principals.get(principal_id)


class _Authorizer:
    def can_approve_pairing(self, actor_id: str) -> bool:
        # Case-insensitive, like a directory-group lookup: the core must hold
        # its distinct-approver rule whatever an authorizer implementation does.
        return actor_id.strip().casefold() == "owner-1"


def _turn(sender: str = "sender-1") -> InboundTurn:
    return InboundTurn(
        channel_kind=ConversationChannelKind.SLACK,
        channel_id="channel-1",
        message_id="message-1",
        sender_id=sender,
        text="query_inventory compute.vm",
    )


def _service(*, mode: ChannelAccessMode = ChannelAccessMode.PAIRING, cap: int = 3):
    return ChannelAccessService(
        modes={ConversationChannelKind.SLACK: mode},
        store=InMemoryChannelPairingStore(),
        identities=_Identities(),
        authorizer=_Authorizer(),
        code_factory=lambda: "ABC123",
        pairing_ttl_seconds=3600,
        max_pending_per_channel=cap,
    )


def _service_with_transitions(transitions: InMemoryRoutingTransitionSink):
    return ChannelAccessService(
        modes={ConversationChannelKind.SLACK: ChannelAccessMode.PAIRING},
        store=InMemoryChannelPairingStore(),
        identities=_Identities(),
        authorizer=_Authorizer(),
        code_factory=lambda: "ABC123",
        transition_sink=transitions,
    )


async def test_unknown_sender_is_denied_until_distinct_approval() -> None:
    service = _service()
    turn = _turn()
    challenge = await service.request_pairing(turn, at=_NOW)
    assert challenge.code == "ABC123"
    assert await service.resolve(turn) is None

    approved = await service.approve(
        ChannelSenderKey(ConversationChannelKind.SLACK, "channel-1", "sender-1"),
        code="ABC123",
        principal_id="operator-1",
        actor_id="owner-1",
        at=_NOW,
    )

    assert approved.code_digest != "ABC123"
    assert (await service.resolve(turn)).id == "operator-1"  # type: ignore[union-attr]
    with pytest.raises(ChannelAccessError, match="already paired"):
        await service.request_pairing(turn, at=_NOW + timedelta(minutes=1))


async def test_invalid_expired_or_reused_code_is_blocked() -> None:
    service = _service()
    turn = _turn()
    await service.request_pairing(turn, at=_NOW)
    sender = ChannelSenderKey(ConversationChannelKind.SLACK, "channel-1", "sender-1")

    with pytest.raises(ChannelAccessError, match="invalid"):
        await service.approve(
            sender,
            code="WRONG",
            principal_id="operator-1",
            actor_id="owner-1",
            at=_NOW,
        )
    with pytest.raises(ChannelAccessError, match="expired"):
        await service.approve(
            sender,
            code="ABC123",
            principal_id="operator-1",
            actor_id="owner-1",
            at=_NOW + timedelta(hours=1),
        )


async def test_pending_cap_and_duplicate_request_are_enforced() -> None:
    service = _service(cap=1)
    await service.request_pairing(_turn("sender-1"), at=_NOW)
    with pytest.raises(ChannelAccessError, match="already pending"):
        await service.request_pairing(_turn("sender-1"), at=_NOW)
    with pytest.raises(ChannelAccessError, match="cap"):
        await service.request_pairing(_turn("sender-2"), at=_NOW)


async def test_expired_request_does_not_consume_pending_capacity() -> None:
    service = _service(cap=1)
    await service.request_pairing(_turn("sender-1"), at=_NOW)

    challenge = await service.request_pairing(
        _turn("sender-2"),
        at=_NOW + timedelta(hours=1),
    )

    assert challenge.code == "ABC123"


async def test_cancel_only_removes_matching_pending_code() -> None:
    service = _service(cap=1)
    turn = _turn("sender-1")
    await service.request_pairing(turn, at=_NOW)

    assert await service.cancel_pairing(turn, code="WRONG") is False
    assert await service.cancel_pairing(turn, code="ABC123") is True
    assert (await service.request_pairing(_turn("sender-2"), at=_NOW)).code == "ABC123"


async def test_pairing_emits_stable_security_transitions() -> None:
    transitions = InMemoryRoutingTransitionSink()
    service = _service_with_transitions(transitions)
    turn = _turn()
    await service.request_pairing(turn, at=_NOW)
    await service.approve(
        ChannelSenderKey(ConversationChannelKind.SLACK, "channel-1", "sender-1"),
        code="ABC123",
        principal_id="operator-1",
        actor_id="owner-1",
        at=_NOW,
    )

    assert [item.domain for item in transitions.transitions] == ["security", "security"]


async def test_disabled_or_allowlist_mode_cannot_self_enroll() -> None:
    for mode in (ChannelAccessMode.DISABLED, ChannelAccessMode.ALLOWLIST):
        service = _service(mode=mode)
        with pytest.raises(ChannelAccessError, match="does not allow pairing"):
            await service.request_pairing(_turn(), at=_NOW)


async def test_unauthorized_or_same_principal_approval_is_blocked() -> None:
    service = _service()
    await service.request_pairing(_turn(), at=_NOW)
    sender = ChannelSenderKey(ConversationChannelKind.SLACK, "channel-1", "sender-1")
    with pytest.raises(ChannelAccessError, match="not authorized"):
        await service.approve(
            sender,
            code="ABC123",
            principal_id="operator-1",
            actor_id="reader-1",
            at=_NOW,
        )


async def test_a_recased_actor_is_not_a_distinct_approver() -> None:
    """Pairing binds a channel sender to a principal, so the approver must be
    someone other than the principal being bound. An identity string is the
    same principal however it is cased.
    """
    service = _service()
    turn = _turn()
    await service.request_pairing(turn, at=_NOW)

    with pytest.raises(ChannelAccessError, match="distinct approver"):
        await service.approve(
            ChannelSenderKey(ConversationChannelKind.SLACK, "channel-1", "sender-1"),
            code="ABC123",
            principal_id="owner-1",
            actor_id="OWNER-1",
            at=_NOW,
        )
