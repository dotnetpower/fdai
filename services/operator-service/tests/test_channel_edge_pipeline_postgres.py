"""Live PostgreSQL join for the Operator semantic channel pipeline."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from fdai_operator_service.families.conversation.channel_delivery_models import (
    ChannelDeliveryState,
    ChannelKind,
)
from fdai_operator_service.families.conversation.channel_edge.models import (
    AuthenticatedInboundTurn,
    ChannelDeliveryReceipt,
    InboundChannelTurn,
)
from fdai_operator_service.families.conversation.channel_edge.pipeline import (
    ChannelDeliveryPipeline,
    ChannelPrincipalContext,
)
from fdai_operator_service.families.conversation.channel_edge.worker import (
    ChannelDeliveryWorker,
    ChannelDeliveryWorkerConfig,
)
from fdai_operator_service.families.conversation.channel_message_ledger import (
    PostgresChannelMessageLedger,
    PostgresChannelMessageLedgerConfig,
)
from fdai_operator_service.families.conversation.contracts import (
    ConversationProposal,
    ConversationResponse,
    ConversationStreamRequest,
    OutboxReceipt,
    PrincipalScope,
    StreamEvent,
)
from fdai_operator_service.families.conversation.postgres_channel_binding import (
    PostgresChannelBindingConfig,
    PostgresPrincipalChannelBindingStore,
)
from fdai_operator_service.families.conversation.postgres_channel_delivery import (
    PostgresChannelDeliveryConfig,
    PostgresChannelDeliveryStore,
)

_NOW = datetime(2026, 8, 19, 21, 0, tzinfo=UTC)


def _dsn(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


class _Principals:
    async def resolve(self, principal_id: str) -> ChannelPrincipalContext:
        return ChannelPrincipalContext(
            scope=PrincipalScope(principal_id, frozenset({"Reader"})),
            scope_ref="scope://pipeline/live",
        )


class _Semantic:
    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        return OutboxReceipt(
            proposal_id="pipeline-live-proposal",
            duplicate=False,
            response=ConversationResponse(body={"accepted": True}, status_code=202),
        )

    async def open(self, request: ConversationStreamRequest) -> _Stream:
        del request
        return _Stream()


class _Stream:
    def __init__(self) -> None:
        self._sent = False

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> StreamEvent:
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return StreamEvent(
            event="done",
            event_id="1",
            data={
                "status": "answered",
                "answer": "The live pipeline evidence is verified.",
                "verification": {
                    "status": "verified",
                    "authority": "ontology-query",
                    "evidence_refs": ["evidence:pipeline-live"],
                },
            },
        )

    async def aclose(self) -> None:
        return None


class _Publisher:
    async def send(self, message):  # type: ignore[no-untyped-def]
        return ChannelDeliveryReceipt(
            channel_kind=message.channel_kind,
            channel_id=message.channel_id,
            message_id="pipeline-live-provider-message",
            degraded_to_text=message.degraded_to_text,
        )


@pytest.mark.integration
async def test_operator_pipeline_joins_all_durable_delivery_owners() -> None:
    admin_dsn = _dsn("FDAI_ADMIN_DATABASE_URL")
    operator_dsn = _dsn("FDAI_DATABASE_URL")
    suffix = uuid4().hex
    channel_id = f"pipeline-channel-{suffix}"
    message_id = f"pipeline-message-{suffix}"
    principal_id = f"pipeline-principal-{suffix}"
    inbound_key = hashlib.sha256(f"slack\0{channel_id}\0{message_id}".encode()).hexdigest()
    delivery_id = f"channel-delivery:{inbound_key}"
    messages = PostgresChannelMessageLedger(
        config=PostgresChannelMessageLedgerConfig(dsn=operator_dsn)
    )
    bindings = PostgresPrincipalChannelBindingStore(
        config=PostgresChannelBindingConfig(dsn=operator_dsn)
    )
    deliveries = PostgresChannelDeliveryStore(
        config=PostgresChannelDeliveryConfig(dsn=operator_dsn)
    )
    semantic = _Semantic()
    pipeline = ChannelDeliveryPipeline(
        messages=messages,
        principals=_Principals(),
        bindings=bindings,
        deliveries=deliveries,
        semantic_outbox=semantic,
        semantic_streams=semantic,
        publishers={ChannelKind.SLACK: _Publisher()},
        clock=lambda: _NOW,
    )
    worker = ChannelDeliveryWorker(
        store=deliveries,
        handler=pipeline,
        config=ChannelDeliveryWorkerConfig(channels=(ChannelKind.SLACK,)),
        clock=lambda: _NOW,
    )
    authenticated = AuthenticatedInboundTurn(
        turn=InboundChannelTurn(
            channel_kind=ChannelKind.SLACK,
            channel_id=channel_id,
            message_id=message_id,
            sender_id=f"pipeline-sender-{suffix}",
            text="Verify the live pipeline evidence.",
            thread_id=f"pipeline-thread-{suffix}",
        ),
        principal_id=principal_id,
        verification_ref=f"pipeline-verification-{suffix}",
    )
    try:
        assert await messages.probe_readiness() is True
        assert await bindings.probe_readiness() is True
        assert await deliveries.probe_readiness() is True
        await worker.initialize()
        first = await pipeline.process(authenticated)
        duplicate = await pipeline.process(authenticated)

        assert first.state is ChannelDeliveryState.DELIVERED
        assert duplicate == type(duplicate)(delivery_id, ChannelDeliveryState.DELIVERED, True)
        snapshot = await deliveries.snapshot(limit=500)
        attempts = [item for item in snapshot.attempts if item.delivery_id == delivery_id]
        acknowledgements = [
            item for item in snapshot.acknowledgements if item.delivery_id == delivery_id
        ]
        assert len(attempts) == 1
        assert attempts[0].outcome is ChannelDeliveryState.DELIVERED
        assert len(acknowledgements) == 1
        assert acknowledgements[0].provider_message_id == "pipeline-live-provider-message"
        async with await psycopg.AsyncConnection.connect(operator_dsn) as connection:
            claim = await connection.execute(
                "SELECT state FROM conversation_channel_message_claim WHERE idempotency_key = %s",
                (inbound_key,),
            )
            assert await claim.fetchone() == ("completed",)
    finally:
        async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
            await connection.execute(
                "DELETE FROM conversation_outbound_delivery WHERE delivery_id = %s",
                (delivery_id,),
            )
            await connection.execute(
                "DELETE FROM principal_conversation_binding WHERE principal_id = %s",
                (principal_id,),
            )
            await connection.execute(
                "DELETE FROM conversation_channel_message_claim WHERE idempotency_key = %s",
                (inbound_key,),
            )
            await connection.commit()
