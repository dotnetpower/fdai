"""Bidirectional channel gateway identity, routing, and dedupe tests."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest

from fdai.core.conversation.busy_input import BusyInputMode
from fdai.core.conversation.busy_input_coordinator import BusyInputCoordinator
from fdai.core.conversation.busy_input_store import InMemoryBusyInputStore
from fdai.core.conversation.channel_gateway import (
    AttachmentIngestionResult,
    ChannelBusyInputModeResolver,
    ChannelDeliveryContext,
    ConversationChannelGateway,
)
from fdai.core.conversation.coordinator import ConversationCoordinator
from fdai.core.conversation.session import ConversationSession, Principal, Role
from fdai.core.conversation.tools import ToolResult
from fdai.shared.providers.conversation_channel import (
    ChannelAttachment,
    ConversationChannelKind,
    InboundTurn,
    OutboundResponse,
)
from fdai.shared.providers.conversation_delivery import (
    InMemoryConversationDeliveryStore,
    OutboundDeliveryRecord,
    new_delivery_record,
)
from fdai.shared.telemetry import InMemoryRoutingTransitionSink


class _ReadTool:
    name = "explore_catalog"
    description = "test"
    rbac_floor = Role.READER
    side_effect_class: Literal["read", "simulate", "approve", "execute", "breakglass"] = "read"
    calls: list[Mapping[str, object]] = []

    def call(self, *, arguments: Mapping[str, object], principal: Principal) -> ToolResult:
        self.calls.append(arguments)
        return ToolResult(status="ok", preview=f"found {arguments['query']}")


class _AttachmentIngestor:
    def __init__(self, result: AttachmentIngestionResult) -> None:
        self.result = result

    async def ingest(
        self,
        *,
        turn: InboundTurn,
        principal: Principal,
    ) -> AttachmentIngestionResult:
        return self.result


class _Resolver:
    def __init__(self, principal: Principal | None) -> None:
        self.principal = principal

    async def resolve(self, turn: InboundTurn) -> Principal | None:
        return self.principal


class _Ledger:
    def __init__(self) -> None:
        self.claimed: set[str] = set()

    async def claim(self, idempotency_key: str) -> bool:
        if idempotency_key in self.claimed:
            return False
        self.claimed.add(idempotency_key)
        return True

    async def release(self, idempotency_key: str) -> None:
        self.claimed.discard(idempotency_key)


class _Adapter:
    def __init__(
        self,
        turns: tuple[InboundTurn, ...] = (),
        *,
        channel_kind: ConversationChannelKind = ConversationChannelKind.TEAMS,
    ) -> None:
        self.turns = turns
        self.channel_kind = channel_kind
        self.sent: list[OutboundResponse] = []

    async def receive(self) -> AsyncIterator[InboundTurn]:
        for turn in self.turns:
            yield turn

    async def send(self, response: OutboundResponse) -> None:
        self.sent.append(response)


class _DeliveryContextResolver:
    async def resolve(
        self,
        *,
        turn: InboundTurn,
        principal: Principal,
        session_id: str,
    ) -> ChannelDeliveryContext:
        del turn
        return ChannelDeliveryContext(
            principal_id=principal.id,
            scope_ref="scope-example",
            conversation_id=session_id,
            binding_id="binding-example",
        )


class _DurableDelivery:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.store = InMemoryConversationDeliveryStore()

    async def submit(
        self,
        *,
        origin_ref: str,
        principal_id: str,
        scope_ref: str,
        conversation_id: str,
        binding_id: str | None,
        response: OutboundResponse,
        send_immediately: bool = True,
    ) -> OutboundDeliveryRecord:
        self.calls.append(
            {
                "origin_ref": origin_ref,
                "principal_id": principal_id,
                "scope_ref": scope_ref,
                "conversation_id": conversation_id,
                "binding_id": binding_id,
                "response": response,
                "send_immediately": send_immediately,
            }
        )
        return await self.store.put(
            new_delivery_record(
                origin_ref=origin_ref,
                principal_id=principal_id,
                scope_ref=scope_ref,
                conversation_id=conversation_id,
                binding_id=binding_id,
                response=response,
                created_at=datetime(2026, 7, 20, 20, 0, tzinfo=UTC),
                freshness=timedelta(minutes=15),
                retention=timedelta(days=30),
            )
        )


def _turn(
    message_id: str = "message-1",
    *,
    channel_kind: ConversationChannelKind = ConversationChannelKind.TEAMS,
) -> InboundTurn:
    return InboundTurn(
        channel_kind=channel_kind,
        channel_id="channel-1",
        message_id=message_id,
        sender_id="sender-1",
        thread_id="thread-1",
        text="explore_catalog storage",
    )


def _gateway(
    principal: Principal | None = None,
    *,
    deny_sender: bool = False,
    attachment_ingestor: _AttachmentIngestor | None = None,
    transition_sink: InMemoryRoutingTransitionSink | None = None,
    busy_input_coordinator: BusyInputCoordinator | None = None,
    busy_input_mode_resolver: ChannelBusyInputModeResolver | None = None,
    outbound_delivery: _DurableDelivery | None = None,
) -> ConversationChannelGateway:
    sessions: dict[str, ConversationSession] = {}

    async def load_session(
        session_id: str, resolved: Principal, channel_id: str
    ) -> ConversationSession:
        return sessions.setdefault(
            session_id,
            ConversationSession(
                session_id=session_id,
                principal=resolved,
                channel_id=channel_id,
            ),
        )

    return ConversationChannelGateway(
        coordinator=ConversationCoordinator(tools=[_ReadTool()]),
        principal_resolver=_Resolver(
            None if deny_sender else (principal or Principal(id="principal-1", role=Role.READER))
        ),
        ledger=_Ledger(),
        load_session=load_session,
        attachment_ingestor=attachment_ingestor,
        transition_sink=transition_sink,
        busy_input_coordinator=busy_input_coordinator,
        busy_input_mode_resolver=busy_input_mode_resolver,
        outbound_delivery=outbound_delivery,
        delivery_context_resolver=(
            _DeliveryContextResolver() if outbound_delivery is not None else None
        ),
    )


class _ModeResolver:
    async def resolve(
        self,
        *,
        session_id: str,  # noqa: ARG002
        principal: Principal,  # noqa: ARG002
    ) -> BusyInputMode:
        return BusyInputMode.STEER


def _busy_session_id(turn: InboundTurn, principal_id: str = "principal-1") -> str:
    thread = turn.thread_id or turn.sender_id
    raw = f"{turn.channel_kind.value}\0{turn.channel_id}\0{thread}\0{principal_id}"
    return "channel:" + hashlib.sha256(raw.encode()).hexdigest()[:40]


async def test_routes_authenticated_turn_back_to_same_thread() -> None:
    adapter = _Adapter((_turn(),))

    await _gateway().run(adapter)

    assert len(adapter.sent) == 1
    assert adapter.sent[0].thread_id == "thread-1"
    assert adapter.sent[0].in_reply_to == "message-1"
    assert adapter.sent[0].text == "found storage"


async def test_channel_gateway_emits_stable_handled_transition() -> None:
    transitions = InMemoryRoutingTransitionSink()
    await _gateway(transition_sink=transitions).handle(adapter=_Adapter(), turn=_turn())

    assert transitions.transitions[0].domain == "channel"
    assert transitions.transitions[0].name == "message.handled"


async def test_duplicate_message_is_not_executed_or_sent_twice() -> None:
    turn = _turn()
    adapter = _Adapter((turn, turn))

    await _gateway().run(adapter)

    assert len(adapter.sent) == 1


async def test_gateway_persists_complete_reply_once_before_provider_delivery() -> None:
    _ReadTool.calls.clear()
    turn = _turn()
    adapter = _Adapter((turn, turn))
    durable = _DurableDelivery()

    await _gateway(outbound_delivery=durable).run(adapter)

    assert adapter.sent == []
    assert len(durable.calls) == 1
    origin_ref = durable.calls[0]["origin_ref"]
    assert isinstance(origin_ref, str) and origin_ref.startswith("channel-message:")
    response = durable.calls[0]["response"]
    assert isinstance(response, OutboundResponse)
    assert response.text == "found storage"
    assert _ReadTool.calls == [{"query": "storage"}]


async def test_unresolved_sender_is_denied_before_coordinator() -> None:
    adapter = _Adapter((_turn(),))
    gateway = _gateway(deny_sender=True)

    await gateway.run(adapter)

    assert adapter.sent == []


async def test_adapter_kind_mismatch_fails_closed() -> None:
    adapter = _Adapter()
    slack_turn = InboundTurn(
        channel_kind=ConversationChannelKind.SLACK,
        channel_id="channel-1",
        message_id="message-1",
        sender_id="sender-1",
        text="explore_catalog storage",
    )

    with pytest.raises(ValueError, match="kind"):
        await _gateway().handle(adapter=adapter, turn=slack_turn)


def test_inbound_turn_rejects_oversized_text() -> None:
    with pytest.raises(ValueError, match="exceeds cap"):
        InboundTurn(
            channel_kind=ConversationChannelKind.WEB,
            channel_id="channel-1",
            message_id="message-1",
            sender_id="sender-1",
            text="x" * 16_001,
        )


async def test_ready_attachment_becomes_citation_never_tool_instruction() -> None:
    _ReadTool.calls.clear()
    turn = replace(
        _turn(),
        attachments=(
            ChannelAttachment(
                source_ref="file-1",
                name="evidence.txt",
                size_bytes=12,
                media_type_hint="text/plain",
            ),
        ),
    )
    response = await _gateway(
        attachment_ingestor=_AttachmentIngestor(
            AttachmentIngestionResult(
                status="ready",
                evidence_refs=("doc:document-1:version-1",),
            )
        )
    ).handle(adapter=_Adapter(), turn=turn)

    assert response is not None
    assert response.evidence_refs == ("doc:document-1:version-1",)
    assert _ReadTool.calls == [{"query": "storage"}]


async def test_rejected_attachment_never_invokes_tool() -> None:
    _ReadTool.calls.clear()
    turn = replace(
        _turn(),
        attachments=(
            ChannelAttachment(
                source_ref="file-1",
                name="evidence.txt",
                size_bytes=12,
                media_type_hint="text/plain",
            ),
        ),
    )
    response = await _gateway(
        attachment_ingestor=_AttachmentIngestor(
            AttachmentIngestionResult(status="rejected", reason="attachment held")
        )
    ).handle(adapter=_Adapter(), turn=turn)

    assert response is not None and response.status == "error"
    assert response.evidence_refs == ()
    assert _ReadTool.calls == []


@pytest.mark.parametrize(
    "channel_kind",
    [ConversationChannelKind.TEAMS, ConversationChannelKind.SLACK],
)
async def test_busy_session_ack_is_identical_for_teams_and_slack(
    channel_kind: ConversationChannelKind,
) -> None:
    _ReadTool.calls.clear()
    turn = _turn(channel_kind=channel_kind)
    coordinator = BusyInputCoordinator(store=InMemoryBusyInputStore())
    session_id = _busy_session_id(turn)
    await coordinator.begin_turn(
        session_id=session_id,
        turn_id="existing-turn",
        principal_id="principal-1",
        mode=BusyInputMode.QUEUE,
    )

    response = await _gateway(busy_input_coordinator=coordinator).handle(
        adapter=_Adapter(channel_kind=channel_kind),
        turn=turn,
    )

    assert response is not None
    assert response.status == "accepted"
    assert response.text == "Follow-up accepted."
    assert response.data["disposition"] == "queued"
    assert response.data["input_id"] == "message-1"
    assert response.data["sequence"] == 0
    assert response.data["duplicate"] is False
    assert _ReadTool.calls == []


async def test_idle_channel_turn_uses_mode_resolver_and_finishes() -> None:
    turn = _turn()
    coordinator = BusyInputCoordinator(store=InMemoryBusyInputStore())
    response = await _gateway(
        busy_input_coordinator=coordinator,
        busy_input_mode_resolver=_ModeResolver(),
    ).handle(adapter=_Adapter(), turn=turn)

    state = await coordinator.status(
        session_id=_busy_session_id(turn),
        principal_id="principal-1",
    )
    assert response is not None and response.status == "ok"
    assert state is not None
    assert state.mode is BusyInputMode.STEER
    assert state.active_turn_id is None
