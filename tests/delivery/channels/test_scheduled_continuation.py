from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fdai.delivery.channels.scheduled_continuation import (
    ScheduledContinuationDeliveryCoordinator,
)
from fdai.shared.providers.conversation_channel import (
    ChannelDeliveryOperation,
    ChannelDeliveryReceipt,
    ChannelThreadMode,
    ConversationChannelKind,
    InboundTurn,
    OutboundResponse,
)
from fdai.shared.providers.conversation_delivery import (
    InMemoryConversationDeliveryStore,
    OutboundDeliveryRecord,
    new_delivery_record,
)
from fdai.shared.providers.scheduled_continuation import (
    ContinuationMode,
    ScheduledConversationAnchor,
    ScheduledResultOrigin,
    anchor_id_for_run,
)
from fdai.shared.providers.testing.user_context import InMemoryConversationHistoryStore
from fdai.shared.providers.user_context import ConversationRecord

NOW = datetime(2026, 7, 20, 21, 0, tzinfo=UTC)


class RecordingChannel:
    def __init__(self, kind: ConversationChannelKind) -> None:
        self.channel_kind = kind
        self.responses: list[OutboundResponse] = []

    async def receive(self) -> AsyncIterator[InboundTurn]:
        if False:
            yield

    async def send(self, response: OutboundResponse) -> ChannelDeliveryReceipt:
        self.responses.append(response)
        return ChannelDeliveryReceipt(
            channel_kind=self.channel_kind,
            channel_id=response.channel_id,
            operation=ChannelDeliveryOperation.POST,
            message_id="provider-message-1",
        )


class RecordingOutboundDelivery:
    def __init__(self) -> None:
        self.store = InMemoryConversationDeliveryStore()
        self.responses: list[OutboundResponse] = []

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
        del send_immediately
        self.responses.append(response)
        return await self.store.put(
            new_delivery_record(
                origin_ref=origin_ref,
                principal_id=principal_id,
                scope_ref=scope_ref,
                conversation_id=conversation_id,
                binding_id=binding_id,
                response=response,
                created_at=NOW,
                freshness=timedelta(minutes=15),
                retention=timedelta(days=30),
            )
        )


def _anchor(
    *,
    channel_kind: ConversationChannelKind,
    mode: ContinuationMode = ContinuationMode.ORIGIN_THREAD,
) -> ScheduledConversationAnchor:
    return ScheduledConversationAnchor(
        anchor_id=anchor_id_for_run(task_id="task-1", run_id="run-1"),
        task_id="task-1",
        run_id="run-1",
        owner_principal_id="principal-a",
        scope_ref="scope-a",
        mode=mode,
        origin=ScheduledResultOrigin(
            channel_kind=channel_kind.value,
            channel_ref="channel-1",
            conversation_ref="conversation-1",
            thread_ref=("thread-1" if mode is ContinuationMode.ORIGIN_THREAD else None),
        ),
        result_digest="a" * 64,
        result_summary="No critical issues were found.",
        evidence_refs=("audit:1",),
        observation_started_at=NOW - timedelta(hours=1),
        observation_ended_at=NOW,
        created_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )


async def test_web_delivery_is_idempotent_provenance_labeled_data() -> None:
    conversations = InMemoryConversationHistoryStore()
    await conversations.create_conversation(
        ConversationRecord(
            conversation_id="conversation-1",
            principal_id="principal-a",
            channel_id="web",
            started_at=NOW - timedelta(days=1),
            last_active=NOW - timedelta(days=1),
        )
    )
    coordinator = ScheduledContinuationDeliveryCoordinator(conversations=conversations)
    anchor = _anchor(channel_kind=ConversationChannelKind.WEB)

    first = await coordinator.deliver(anchor)
    second = await coordinator.deliver(anchor)

    assert first == second
    turns = await conversations.list_turns(
        principal_id="principal-a",
        conversation_id="conversation-1",
    )
    assert len(turns) == 1
    assert "run=run-1" in turns[0].content
    assert "evidence=audit:1" in turns[0].content
    assert turns[0].metadata["instruction_authority"] == "none"
    assert turns[0].metadata["result_digest"] == "a" * 64


async def test_slack_origin_and_teams_dedicated_thread_intent_preserve_anchor_metadata() -> None:
    conversations = InMemoryConversationHistoryStore()
    slack = RecordingChannel(ConversationChannelKind.SLACK)
    teams = RecordingChannel(ConversationChannelKind.TEAMS)
    coordinator = ScheduledContinuationDeliveryCoordinator(
        conversations=conversations,
        channels={
            ConversationChannelKind.SLACK: slack,
            ConversationChannelKind.TEAMS: teams,
        },
    )

    await coordinator.deliver(_anchor(channel_kind=ConversationChannelKind.SLACK))
    await coordinator.deliver(
        _anchor(
            channel_kind=ConversationChannelKind.TEAMS,
            mode=ContinuationMode.DEDICATED_THREAD,
        )
    )

    assert slack.responses[0].thread_id == "thread-1"
    assert slack.responses[0].thread_mode is ChannelThreadMode.ORIGIN
    assert teams.responses[0].thread_id is None
    assert teams.responses[0].thread_mode is ChannelThreadMode.DEDICATED
    assert teams.responses[0].data["scheduled_continuation_anchor_id"] == anchor_id_for_run(
        task_id="task-1", run_id="run-1"
    )


async def test_external_scheduled_result_uses_durable_delivery_without_regeneration() -> None:
    conversations = InMemoryConversationHistoryStore()
    channel = RecordingChannel(ConversationChannelKind.SLACK)
    durable = RecordingOutboundDelivery()
    coordinator = ScheduledContinuationDeliveryCoordinator(
        conversations=conversations,
        channels={ConversationChannelKind.SLACK: channel},
        outbound_delivery=durable,
    )
    anchor = _anchor(channel_kind=ConversationChannelKind.SLACK)

    first = await coordinator.deliver(anchor)
    second = await coordinator.deliver(anchor)

    assert first == second
    assert channel.responses == []
    assert durable.responses[0].text == anchor.result_summary
    assert durable.responses[0].data["result_digest"] == anchor.result_digest
