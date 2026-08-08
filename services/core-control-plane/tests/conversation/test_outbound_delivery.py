from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fdai.core.conversation.outbound_delivery import (
    DurableOutboundDeliveryConfig,
    DurableOutboundDeliveryCoordinator,
)
from fdai.shared.providers.conversation_channel import (
    ChannelDeliveryError,
    ChannelDeliveryOperation,
    ChannelDeliveryReceipt,
    ConversationChannelKind,
    InboundTurn,
    OutboundResponse,
)
from fdai.shared.providers.conversation_delivery import (
    InMemoryConversationDeliveryStore,
    OutboundDeliveryRecord,
    OutboundDeliveryState,
)

NOW = datetime(2026, 7, 20, 14, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> datetime:
        return self.value


class _Channel:
    channel_kind = ConversationChannelKind.SLACK

    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.responses: list[OutboundResponse] = []

    async def receive(self) -> AsyncIterator[InboundTurn]:
        if False:
            yield

    async def send(self, response: OutboundResponse) -> ChannelDeliveryReceipt:
        self.responses.append(response)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, ChannelDeliveryReceipt)
        return outcome


def _receipt() -> ChannelDeliveryReceipt:
    return ChannelDeliveryReceipt(
        channel_kind=ConversationChannelKind.SLACK,
        channel_id="channel-example",
        operation=ChannelDeliveryOperation.POST,
        message_id="provider-message-example",
    )


def _response() -> OutboundResponse:
    return OutboundResponse(
        channel_kind=ConversationChannelKind.SLACK,
        channel_id="channel-example",
        in_reply_to="message-example",
        thread_id="thread-example",
        status="ok",
        text="Stored once",
    )


def _coordinator(
    store: InMemoryConversationDeliveryStore,
    channel: _Channel,
    clock: _Clock,
    *,
    max_attempts: int = 3,
) -> DurableOutboundDeliveryCoordinator:
    return DurableOutboundDeliveryCoordinator(
        store=store,
        channels={ConversationChannelKind.SLACK: channel},
        config=DurableOutboundDeliveryConfig(
            worker_id="worker-example",
            max_attempts=max_attempts,
            base_retry_seconds=1,
        ),
        clock=clock,
    )


async def _submit(
    coordinator: DurableOutboundDeliveryCoordinator,
) -> OutboundDeliveryRecord:
    return await coordinator.submit(
        origin_ref="turn:example",
        principal_id="principal-example",
        scope_ref="scope-example",
        conversation_id="conversation-example",
        binding_id="binding-example",
        response=_response(),
    )


async def test_confirmed_receipt_delivers_exact_persisted_response_once() -> None:
    store = InMemoryConversationDeliveryStore()
    channel = _Channel([_receipt()])
    coordinator = _coordinator(store, channel, _Clock())

    delivered = await _submit(coordinator)
    duplicate = await _submit(coordinator)

    assert delivered.state is OutboundDeliveryState.DELIVERED
    assert duplicate == delivered
    assert channel.responses == [_response()]


async def test_crash_during_send_is_ambiguous_and_never_auto_retried() -> None:
    store = InMemoryConversationDeliveryStore()
    channel = _Channel([KeyboardInterrupt(), _receipt()])
    coordinator = _coordinator(store, channel, _Clock())

    ambiguous = await _submit(coordinator)
    repeated = await coordinator.deliver(ambiguous.delivery_id)

    assert ambiguous.state is OutboundDeliveryState.AMBIGUOUS
    assert ambiguous.duplicate_risk is True
    assert repeated == ambiguous
    assert channel.responses == [_response()]


async def test_definitive_failure_retries_same_payload_then_delivers() -> None:
    store = InMemoryConversationDeliveryStore()
    channel = _Channel(
        [
            ChannelDeliveryError(
                "provider rejected",
                code="provider_rejected",
                acknowledgement_ambiguous=False,
            ),
            _receipt(),
        ]
    )
    clock = _Clock()
    coordinator = _coordinator(store, channel, clock)

    failed = await _submit(coordinator)
    clock.value += timedelta(seconds=1)
    results = await coordinator.drain_due()

    assert failed.state is OutboundDeliveryState.FAILED
    assert results[0].state is OutboundDeliveryState.DELIVERED
    assert channel.responses == [_response(), _response()]


async def test_retry_storm_is_bounded_to_abandoned() -> None:
    store = InMemoryConversationDeliveryStore()
    failure = ChannelDeliveryError(
        "provider rejected",
        code="provider_rejected",
        acknowledgement_ambiguous=False,
    )
    channel = _Channel([failure, failure, _receipt()])
    clock = _Clock()
    coordinator = _coordinator(store, channel, clock, max_attempts=2)

    first = await _submit(coordinator)
    clock.value = first.due_at
    abandoned = (await coordinator.drain_due())[0]

    assert abandoned.state is OutboundDeliveryState.ABANDONED
    assert len(channel.responses) == 2


async def test_startup_reconciliation_marks_lost_sender_ambiguous() -> None:
    store = InMemoryConversationDeliveryStore()
    clock = _Clock()
    coordinator = _coordinator(store, _Channel([_receipt()]), clock)
    pending = await coordinator.submit(
        origin_ref="turn:example",
        principal_id="principal-example",
        scope_ref="scope-example",
        conversation_id="conversation-example",
        binding_id="binding-example",
        response=_response(),
        send_immediately=False,
    )
    await store.claim(
        delivery_id=pending.delivery_id,
        now=NOW,
        worker_id="lost-worker",
        lease_seconds=30,
    )
    clock.value += timedelta(seconds=31)

    assert await coordinator.reconcile_startup() == 1
    reconciled = await store.get(pending.delivery_id)
    assert reconciled is not None and reconciled.state is OutboundDeliveryState.AMBIGUOUS


async def test_crash_before_send_leaves_pending_response_for_startup_drain() -> None:
    store = InMemoryConversationDeliveryStore()
    channel = _Channel([_receipt()])
    clock = _Clock()
    coordinator = _coordinator(store, channel, clock)

    pending = await coordinator.submit(
        origin_ref="turn:before-send",
        principal_id="principal-example",
        scope_ref="scope-example",
        conversation_id="conversation-example",
        binding_id="binding-example",
        response=_response(),
        send_immediately=False,
    )
    delivered = (await coordinator.drain_due())[0]

    assert pending.state is OutboundDeliveryState.PENDING
    assert delivered.state is OutboundDeliveryState.DELIVERED
    assert channel.responses == [_response()]


async def test_provider_receipt_before_local_ack_reconciles_ambiguous() -> None:
    class _CrashBeforeAckStore(InMemoryConversationDeliveryStore):
        async def finish(self, **kwargs: object) -> OutboundDeliveryRecord:
            raise KeyboardInterrupt

    store = _CrashBeforeAckStore()
    channel = _Channel([_receipt(), _receipt()])
    clock = _Clock()
    coordinator = _coordinator(store, channel, clock)

    try:
        await _submit(coordinator)
    except KeyboardInterrupt:
        pass
    clock.value += timedelta(seconds=31)
    assert await coordinator.reconcile_startup() == 1
    record = (await store.snapshot()).deliveries[0]

    assert record.state is OutboundDeliveryState.AMBIGUOUS
    assert record.duplicate_risk is True
    assert channel.responses == [_response()]


async def test_concurrent_senders_allow_only_one_delivery_claim() -> None:
    store = InMemoryConversationDeliveryStore()
    pending = await store.put(
        await _coordinator(store, _Channel([_receipt()]), _Clock()).submit(
            origin_ref="turn:concurrent",
            principal_id="principal-example",
            scope_ref="scope-example",
            conversation_id="conversation-example",
            binding_id="binding-example",
            response=_response(),
            send_immediately=False,
        )
    )

    claims = await asyncio.gather(
        store.claim(
            delivery_id=pending.delivery_id,
            now=NOW,
            worker_id="worker-a",
            lease_seconds=30,
        ),
        store.claim(
            delivery_id=pending.delivery_id,
            now=NOW,
            worker_id="worker-b",
            lease_seconds=30,
        ),
    )

    assert sum(claim is not None for claim in claims) == 1
