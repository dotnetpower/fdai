"""Semantic-to-delivery ownership tests for the Operator channel edge."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from fdai_operator_service.families.conversation.channel_delivery_models import (
    ChannelAdapterBreaker,
    ChannelBindingState,
    ChannelBreakerMode,
    ChannelDeliveryRecord,
    ChannelDeliveryState,
    ChannelKind,
    PrincipalChannelBinding,
)
from fdai_operator_service.families.conversation.channel_edge.models import (
    AuthenticatedInboundTurn,
    ChannelDeliveryError,
    ChannelDeliveryReceipt,
    InboundChannelTurn,
)
from fdai_operator_service.families.conversation.channel_edge.pipeline import (
    ChannelDeliveryPipeline,
    ChannelPrincipalContext,
)
from fdai_operator_service.families.conversation.contracts import (
    ConversationProposal,
    ConversationStreamRequest,
    OutboxReceipt,
    PrincipalScope,
    StreamEvent,
)

_NOW = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)


class _Messages:
    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.completed: set[str] = set()
        self.released: set[str] = set()

    async def claim(self, key: str) -> bool:
        if key in self.keys:
            return False
        self.keys.add(key)
        return True

    async def complete(self, key: str) -> None:
        self.completed.add(key)

    async def release(self, key: str) -> None:
        self.keys.discard(key)
        self.released.add(key)


class _Principals:
    async def resolve(self, principal_id: str) -> ChannelPrincipalContext:
        return ChannelPrincipalContext(
            scope=PrincipalScope(principal_id, frozenset({"Reader"})),
            scope_ref="scope://operator/example",
        )


class _Bindings:
    def __init__(self) -> None:
        self.values: dict[str, PrincipalChannelBinding] = {}

    async def create(self, binding: PrincipalChannelBinding) -> PrincipalChannelBinding:
        current = self.values.setdefault(binding.binding_id, binding)
        return current

    async def get(self, binding_id: str) -> PrincipalChannelBinding | None:
        return self.values.get(binding_id)


class _Outbox:
    def __init__(self) -> None:
        self.proposals: list[ConversationProposal] = []

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        self.proposals.append(proposal)
        return OutboxReceipt(  # type: ignore[call-arg]
            proposal_id="proposal-example",
            duplicate=False,
            response=None,
        )


class _Stream:
    def __init__(self, event: StreamEvent | None) -> None:
        self._event = event
        self._sent = False
        self.closed = False

    def __aiter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __anext__(self) -> StreamEvent:
        if self._sent or self._event is None:
            raise StopAsyncIteration
        self._sent = True
        return self._event

    async def aclose(self) -> None:
        self.closed = True


class _Streams:
    def __init__(self, terminal: dict[str, object] | None) -> None:
        self.terminal = terminal
        self.requests: list[ConversationStreamRequest] = []
        self.last_stream: _Stream | None = None

    async def open(self, request: ConversationStreamRequest) -> _Stream:
        self.requests.append(request)
        event = StreamEvent(event="done", data=self.terminal) if self.terminal is not None else None  # type: ignore[arg-type]
        self.last_stream = _Stream(event)
        return self.last_stream


class _FailOnceStreams(_Streams):
    def __init__(self, terminal: dict[str, object]) -> None:
        super().__init__(terminal)
        self.failed = False

    async def open(self, request: ConversationStreamRequest) -> _Stream:
        if not self.failed:
            self.failed = True
            raise RuntimeError("simulated process loss after binding")
        return await super().open(request)


class _BlockingStreams(_Streams):
    async def open(self, request: ConversationStreamRequest) -> _Stream:
        del request
        await asyncio.Event().wait()
        raise AssertionError("blocking stream unexpectedly resumed")


class _Deliveries:
    def __init__(self) -> None:
        self.values: dict[str, ChannelDeliveryRecord] = {}
        self.finished: list[ChannelDeliveryRecord] = []
        self.breaker_mode = ChannelBreakerMode.CLOSED

    async def put(self, record: ChannelDeliveryRecord) -> ChannelDeliveryRecord:
        return self.values.setdefault(record.delivery_id, record)

    async def get(self, delivery_id: str) -> ChannelDeliveryRecord | None:
        return self.values.get(delivery_id)

    async def get_breaker(self, adapter_id: str) -> ChannelAdapterBreaker | None:
        return ChannelAdapterBreaker(
            adapter_id=adapter_id,
            channel_kind=ChannelKind.SLACK,
            mode=self.breaker_mode,
            updated_at=_NOW,
        )

    async def claim(self, *, delivery_id: str, **_kwargs: object) -> ChannelDeliveryRecord | None:
        current = self.values.get(delivery_id)
        if current is None or current.state not in {
            ChannelDeliveryState.PENDING,
            ChannelDeliveryState.FAILED,
        }:
            return None
        claimed = replace(
            current,
            state=ChannelDeliveryState.SENDING,
            attempt_count=current.attempt_count + 1,
            lease_owner="operator-channel-edge",
            lease_expires_at=_NOW,
        )
        self.values[delivery_id] = claimed
        return claimed

    async def finish(
        self,
        *,
        delivery_id: str,
        state: ChannelDeliveryState,
        error_code: str | None = None,
        next_due_at: datetime | None = None,
        **_kwargs: object,
    ) -> ChannelDeliveryRecord:
        current = self.values[delivery_id]
        closed = replace(
            current,
            state=state,
            due_at=next_due_at or current.due_at,
            lease_owner=None,
            lease_expires_at=None,
            last_error_code=error_code,
            duplicate_risk=state is ChannelDeliveryState.AMBIGUOUS,
            terminal_at=_NOW if state.immutable else None,
        )
        self.values[delivery_id] = closed
        self.finished.append(closed)
        return closed


class _Publisher:
    def __init__(self, error: ChannelDeliveryError | None = None) -> None:
        self.error = error
        self.messages = []

    async def send(self, message):  # type: ignore[no-untyped-def]
        self.messages.append(message)
        if self.error is not None:
            raise self.error
        return ChannelDeliveryReceipt(
            channel_kind=message.channel_kind,
            channel_id=message.channel_id,
            message_id="provider-message-example",
        )


def _terminal() -> dict[str, object]:
    return {
        "status": "answered",
        "answer": "The verified incident is stable.",
        "verification": {
            "status": "verified",
            "authority": "ontology-query",
            "evidence_refs": ["evidence:incident-example"],
        },
    }


def _turn() -> AuthenticatedInboundTurn:
    return AuthenticatedInboundTurn(
        turn=InboundChannelTurn(
            channel_kind=ChannelKind.SLACK,
            channel_id="channel-example",
            message_id="message-example",
            sender_id="vendor-user-example",
            text="Show current incident evidence.",
            thread_id="thread-example",
        ),
        principal_id="principal-example",
        verification_ref="slack-mapping:example",
    )


def _pipeline(
    *,
    messages: _Messages,
    streams: _Streams,
    deliveries: _Deliveries,
    publisher: _Publisher,
    bindings: _Bindings | None = None,
) -> tuple[ChannelDeliveryPipeline, _Outbox]:
    outbox = _Outbox()
    return (
        ChannelDeliveryPipeline(
            messages=messages,
            principals=_Principals(),
            bindings=bindings or _Bindings(),
            deliveries=deliveries,
            semantic_outbox=outbox,  # type: ignore[arg-type]
            semantic_streams=streams,
            publishers={ChannelKind.SLACK: publisher},
            clock=lambda: _NOW,
        ),
        outbox,
    )


async def test_pipeline_completes_inbound_only_after_durable_delivery_and_sends() -> None:
    messages = _Messages()
    streams = _Streams(_terminal())
    deliveries = _Deliveries()
    publisher = _Publisher()
    pipeline, outbox = _pipeline(
        messages=messages,
        streams=streams,
        deliveries=deliveries,
        publisher=publisher,
    )

    result = await pipeline.process(_turn())

    assert result.state is ChannelDeliveryState.DELIVERED
    assert len(messages.completed) == 1
    assert len(outbox.proposals) == 1
    assert outbox.proposals[0].scope.subject_id == "principal-example"
    assert len(deliveries.values) == 1
    assert publisher.messages[0].channel_id == "channel-example"
    assert streams.last_stream is not None and streams.last_stream.closed is True


async def test_pipeline_duplicate_reuses_durable_delivery_without_semantic_work() -> None:
    messages = _Messages()
    streams = _Streams(_terminal())
    deliveries = _Deliveries()
    pipeline, outbox = _pipeline(
        messages=messages,
        streams=streams,
        deliveries=deliveries,
        publisher=_Publisher(),
    )

    first = await pipeline.process(_turn())
    duplicate = await pipeline.process(_turn())

    assert duplicate.delivery_id == first.delivery_id
    assert duplicate.state is ChannelDeliveryState.DELIVERED
    assert duplicate.duplicate is True
    assert len(outbox.proposals) == 1


async def test_pipeline_releases_inbound_when_semantic_stream_has_no_terminal() -> None:
    messages = _Messages()
    pipeline, _outbox = _pipeline(
        messages=messages,
        streams=_Streams(None),
        deliveries=_Deliveries(),
        publisher=_Publisher(),
    )

    try:
        await pipeline.process(_turn())
    except ValueError as exc:
        assert "before terminal" in str(exc)
    else:
        raise AssertionError("nonterminal semantic stream was accepted")
    assert len(messages.released) == 1
    assert not messages.completed


async def test_pipeline_reuses_timestamped_binding_after_pre_delivery_process_loss() -> None:
    messages = _Messages()
    streams = _FailOnceStreams(_terminal())
    deliveries = _Deliveries()
    bindings = _Bindings()
    outbox = _Outbox()
    moments = iter((_NOW, _NOW, _NOW.replace(minute=1), _NOW.replace(minute=1)))
    pipeline = ChannelDeliveryPipeline(
        messages=messages,
        principals=_Principals(),
        bindings=bindings,
        deliveries=deliveries,
        semantic_outbox=outbox,  # type: ignore[arg-type]
        semantic_streams=streams,
        publishers={ChannelKind.SLACK: _Publisher()},
        clock=lambda: next(moments),
    )

    try:
        await pipeline.process(_turn())
    except RuntimeError as exc:
        assert "process loss" in str(exc)
    else:
        raise AssertionError("simulated process loss did not escape")
    result = await pipeline.process(_turn())

    assert result.state is ChannelDeliveryState.DELIVERED
    assert len(bindings.values) == 1


async def test_pipeline_closes_ambiguous_ack_as_immutable_duplicate_risk() -> None:
    messages = _Messages()
    deliveries = _Deliveries()
    publisher = _Publisher(
        ChannelDeliveryError(
            "ack lost",
            code="transport_error",
            acknowledgement_ambiguous=True,
        )
    )
    pipeline, _outbox = _pipeline(
        messages=messages,
        streams=_Streams(_terminal()),
        deliveries=deliveries,
        publisher=publisher,
    )

    result = await pipeline.process(_turn())

    assert result.state is ChannelDeliveryState.AMBIGUOUS
    record = deliveries.values[result.delivery_id]
    assert record.duplicate_risk is True
    assert record.terminal_at == _NOW


async def test_pipeline_persists_but_does_not_claim_when_breaker_is_open() -> None:
    messages = _Messages()
    deliveries = _Deliveries()
    deliveries.breaker_mode = ChannelBreakerMode.OPEN
    publisher = _Publisher()
    pipeline, _outbox = _pipeline(
        messages=messages,
        streams=_Streams(_terminal()),
        deliveries=deliveries,
        publisher=publisher,
    )

    result = await pipeline.process(_turn())

    assert result.state is ChannelDeliveryState.PENDING
    assert messages.completed
    assert not publisher.messages


async def test_pipeline_cancellation_releases_pre_delivery_inbound_claim() -> None:
    messages = _Messages()
    pipeline, _outbox = _pipeline(
        messages=messages,
        streams=_BlockingStreams(None),
        deliveries=_Deliveries(),
        publisher=_Publisher(),
    )

    task = asyncio.create_task(pipeline.process(_turn()))
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("pipeline cancellation did not propagate")
    assert len(messages.released) == 1
    assert not messages.completed


async def test_due_delivery_abandons_a_revoked_binding_without_provider_io() -> None:
    messages = _Messages()
    deliveries = _Deliveries()
    deliveries.breaker_mode = ChannelBreakerMode.OPEN
    bindings = _Bindings()
    publisher = _Publisher()
    pipeline, _outbox = _pipeline(
        messages=messages,
        streams=_Streams(_terminal()),
        deliveries=deliveries,
        publisher=publisher,
        bindings=bindings,
    )
    result = await pipeline.process(_turn())
    record = await deliveries.claim(delivery_id=result.delivery_id)
    assert record is not None and record.binding_id is not None
    binding = bindings.values[record.binding_id]
    bindings.values[record.binding_id] = replace(
        binding,
        state=ChannelBindingState.REVOKED,
        revoked_by="operator-example",
        revoked_at=_NOW,
    )

    closed = await pipeline.deliver_claimed(record)

    assert closed.state is ChannelDeliveryState.ABANDONED
    assert closed.last_error_code == "binding_unavailable"
    assert not publisher.messages


async def test_due_delivery_abandons_a_cross_scope_binding_without_provider_io() -> None:
    messages = _Messages()
    deliveries = _Deliveries()
    deliveries.breaker_mode = ChannelBreakerMode.OPEN
    bindings = _Bindings()
    publisher = _Publisher()
    pipeline, _outbox = _pipeline(
        messages=messages,
        streams=_Streams(_terminal()),
        deliveries=deliveries,
        publisher=publisher,
        bindings=bindings,
    )
    result = await pipeline.process(_turn())
    record = await deliveries.claim(delivery_id=result.delivery_id)
    assert record is not None and record.binding_id is not None
    binding = bindings.values[record.binding_id]
    bindings.values[record.binding_id] = replace(
        binding,
        scope_ref="scope://operator/other",
        endpoint=replace(binding.endpoint, scope_ref="scope://operator/other"),
    )

    closed = await pipeline.deliver_claimed(record)

    assert closed.state is ChannelDeliveryState.ABANDONED
    assert closed.last_error_code == "binding_unavailable"
    assert not publisher.messages
