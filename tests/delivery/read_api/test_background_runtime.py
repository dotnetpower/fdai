from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.background_task import (
    BackgroundTask,
    BackgroundTaskAttempt,
    BackgroundTaskBudget,
    BackgroundTaskKind,
    BackgroundTaskOrigin,
    BackgroundTaskResult,
    BackgroundTaskStatus,
    BackgroundTaskUsage,
)
from fdai.core.conversation.principal_binding import InMemoryPrincipalConversationBindingStore
from fdai.delivery.read_api.routes.background_runtime import (
    BackgroundCompletionBindingResolver,
    ConversationBackgroundTaskCompletionSink,
)
from fdai.shared.providers.conversation_channel import (
    ConversationChannelKind,
    OutboundResponse,
)
from fdai.shared.providers.conversation_delivery import (
    InMemoryConversationDeliveryStore,
    OutboundDeliveryRecord,
    PrincipalConversationBinding,
    VerifiedChannelEndpoint,
    new_delivery_record,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.testing.user_context import InMemoryConversationHistoryStore
from fdai.shared.providers.user_context import ConversationRecord


class _Outbound:
    def __init__(self, *, now: datetime) -> None:
        self.now = now
        self.store = InMemoryConversationDeliveryStore()
        self.responses: list[OutboundResponse] = []
        self.send_immediately: list[bool] = []

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
        self.responses.append(response)
        self.send_immediately.append(send_immediately)
        return await self.store.put(
            new_delivery_record(
                origin_ref=origin_ref,
                principal_id=principal_id,
                scope_ref=scope_ref,
                conversation_id=conversation_id,
                binding_id=binding_id,
                response=response,
                created_at=self.now,
                freshness=timedelta(minutes=15),
                retention=timedelta(days=30),
            )
        )


async def test_completion_sink_appends_one_provenance_labeled_turn() -> None:
    history = InMemoryConversationHistoryStore()
    now = datetime(2026, 7, 20, tzinfo=UTC)
    await history.create_conversation(
        ConversationRecord(
            conversation_id="conversation-one",
            principal_id="operator-one",
            channel_id="channel-one",
            started_at=now,
            last_active=now,
        )
    )
    task = BackgroundTask(
        task_id="background-one",
        owner_principal_id="operator-one",
        origin=BackgroundTaskOrigin("conversation-one", "web", "channel-one"),
        kind=BackgroundTaskKind.READ_ONLY_INVESTIGATION,
        prompt="Inspect bounded evidence.",
        context_digest="sha256:context",
        capability_profile_id="background.read-only",
        budget=BackgroundTaskBudget(),
        correlation_id="correlation-one",
        idempotency_key="idempotency-one",
        created_at=now,
        retention_until=now + timedelta(days=30),
    )
    result = BackgroundTaskResult(
        summary="Completed.",
        evidence_refs=(),
        terminal_reason="completed",
        usage=BackgroundTaskUsage(),
        started_at=now,
        finished_at=now,
    )
    attempt = BackgroundTaskAttempt(
        attempt_id="background-one:1",
        task=task,
        attempt_number=1,
        status=BackgroundTaskStatus.SUCCEEDED,
        revision=4,
        updated_at=now,
        result=result,
    )
    audit = InMemoryStateStore()
    sink = ConversationBackgroundTaskCompletionSink(history=history, audit=audit)

    await sink.publish(attempt)
    await sink.publish(attempt)
    turns = await history.list_turns(
        principal_id="operator-one",
        conversation_id="conversation-one",
    )

    assert len(turns) == 1
    assert turns[0].content == "[Background task result: background-one]\nCompleted."
    assert turns[0].metadata["trusted"] == "false"
    assert turns[0].idempotency_key == "background-completion:background-one:1"
    audit_entries = tuple(audit.audit_entries)
    assert len(audit_entries) == 1
    assert audit_entries[0]["entry"]["action_kind"] == "background-task.completed"


async def test_completion_sink_enqueues_one_verified_origin_delivery() -> None:
    history = InMemoryConversationHistoryStore()
    bindings = InMemoryPrincipalConversationBindingStore()
    now = datetime(2026, 7, 20, tzinfo=UTC)
    await history.create_conversation(
        ConversationRecord(
            conversation_id="conversation-one",
            principal_id="operator-one",
            channel_id="channel-one",
            started_at=now,
            last_active=now,
        )
    )
    await bindings.create(
        PrincipalConversationBinding(
            binding_id="binding-one",
            principal_id="operator-one",
            scope_ref="scope-one",
            conversation_id="conversation-one",
            endpoint=VerifiedChannelEndpoint(
                principal_id="operator-one",
                scope_ref="scope-one",
                channel_kind=ConversationChannelKind.WEB,
                channel_id="channel-one",
                sender_id="sender-one",
                thread_id=None,
                verification_ref="verification-one",
                verified_at=now,
            ),
            created_by="operator-one",
            created_at=now,
        )
    )
    task = BackgroundTask(
        task_id="background-delivery-one",
        owner_principal_id="operator-one",
        origin=BackgroundTaskOrigin(
            "conversation-one",
            "web",
            "channel-one",
            message_id="message-one",
        ),
        kind=BackgroundTaskKind.READ_ONLY_INVESTIGATION,
        prompt="Inspect vm-01 state.",
        context_digest="sha256:context",
        capability_profile_id="background.read-only",
        budget=BackgroundTaskBudget(),
        correlation_id="correlation-one",
        idempotency_key="idempotency-one",
        created_at=now,
        retention_until=now + timedelta(days=30),
    )
    result = BackgroundTaskResult(
        summary="Completed.",
        evidence_refs=("evidence-one",),
        terminal_reason="matched",
        usage=BackgroundTaskUsage(tool_calls=2),
        started_at=now,
        finished_at=now,
    )
    attempt = BackgroundTaskAttempt(
        attempt_id="background-delivery-one:1",
        task=task,
        attempt_number=1,
        status=BackgroundTaskStatus.SUCCEEDED,
        revision=4,
        updated_at=now,
        result=result,
    )
    audit = InMemoryStateStore()
    outbound = _Outbound(now=now)
    sink = ConversationBackgroundTaskCompletionSink(
        history=history,
        audit=audit,
        outbound_delivery=outbound,
        binding_resolver=BackgroundCompletionBindingResolver(bindings=bindings),
    )

    await sink.publish(attempt)
    await sink.publish(attempt)
    snapshot = await outbound.store.snapshot()
    turns = await history.list_turns(
        principal_id="operator-one",
        conversation_id="conversation-one",
    )

    assert len(turns) == 1
    assert len(snapshot.deliveries) == 1
    assert outbound.send_immediately == [False, False]
    assert outbound.responses[0].in_reply_to == "message-one"
    assert outbound.responses[0].evidence_refs == ("evidence-one",)
    assert attempt.result == result
    actions = [entry["entry"]["action_kind"] for entry in audit.audit_entries]
    assert actions.count("background-task.completed") == 1
    assert actions.count("background-task.delivery-enqueued") == 1
