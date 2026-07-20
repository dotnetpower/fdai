"""Route persisted scheduled-result anchors to web, Slack, or Teams threads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from fdai.shared.providers.conversation_channel import (
    ChannelDeliveryReceipt,
    ChannelThreadMode,
    ConversationChannelAdapter,
    ConversationChannelKind,
    OutboundResponse,
)
from fdai.shared.providers.conversation_delivery import OutboundDeliveryRecord
from fdai.shared.providers.scheduled_continuation import (
    ContinuationMode,
    ScheduledConversationAnchor,
    scheduled_result_fact_text,
)
from fdai.shared.providers.user_context import (
    ConversationHistoryStore,
    ConversationTurnRecord,
    ConversationTurnRole,
)


class ScheduledOutboundDelivery(Protocol):
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
    ) -> OutboundDeliveryRecord: ...


class ScheduledContinuationDeliveryCoordinator:
    """Deliver one already-persisted anchor without regenerating its result."""

    def __init__(
        self,
        *,
        conversations: ConversationHistoryStore,
        channels: Mapping[ConversationChannelKind, ConversationChannelAdapter] = {},
        outbound_delivery: ScheduledOutboundDelivery | None = None,
    ) -> None:
        self._conversations = conversations
        self._channels = dict(channels)
        self._outbound_delivery = outbound_delivery

    async def deliver(
        self, anchor: ScheduledConversationAnchor
    ) -> ConversationTurnRecord | ChannelDeliveryReceipt | OutboundDeliveryRecord:
        try:
            channel_kind = ConversationChannelKind(anchor.origin.channel_kind)
        except ValueError as exc:
            raise ValueError("scheduled continuation channel kind is unsupported") from exc
        if channel_kind is ConversationChannelKind.WEB:
            return await self._deliver_web(anchor)
        channel = self._channels.get(channel_kind)
        if channel is None:
            raise RuntimeError(
                f"scheduled continuation channel {channel_kind.value!r} is unavailable"
            )
        dedicated = anchor.mode is ContinuationMode.DEDICATED_THREAD
        response = OutboundResponse(
            channel_kind=channel_kind,
            channel_id=anchor.origin.channel_ref,
            in_reply_to=anchor.origin.thread_ref or anchor.origin.conversation_ref,
            thread_id=None if dedicated else anchor.origin.thread_ref,
            thread_mode=(ChannelThreadMode.DEDICATED if dedicated else ChannelThreadMode.ORIGIN),
            status="scheduled_result",
            text=anchor.result_summary,
            data={
                "scheduled_continuation_anchor_id": anchor.anchor_id,
                "scheduled_run_id": anchor.run_id,
                "result_digest": anchor.result_digest,
            },
            evidence_refs=anchor.evidence_refs,
        )
        if self._outbound_delivery is not None:
            return await self._outbound_delivery.submit(
                origin_ref=f"scheduled-continuation:{anchor.anchor_id}",
                principal_id=anchor.owner_principal_id,
                scope_ref=anchor.scope_ref,
                conversation_id=anchor.origin.conversation_ref,
                binding_id=None,
                response=response,
            )
        receipt = await channel.send(response)
        if receipt is None or receipt.message_id is None:
            raise RuntimeError("scheduled continuation delivery was not acknowledged")
        return receipt

    async def _deliver_web(self, anchor: ScheduledConversationAnchor) -> ConversationTurnRecord:
        conversation = await self._conversations.get_conversation(
            principal_id=anchor.owner_principal_id,
            conversation_id=anchor.origin.conversation_ref,
        )
        if conversation is None:
            raise RuntimeError("scheduled continuation origin conversation was not found")
        return await self._conversations.append_turn(
            ConversationTurnRecord(
                turn_id=f"turn:{anchor.anchor_id}:scheduled-result",
                conversation_id=anchor.origin.conversation_ref,
                principal_id=anchor.owner_principal_id,
                turn_index=0,
                role=ConversationTurnRole.ASSISTANT,
                content=scheduled_result_fact_text(anchor),
                recorded_at=anchor.created_at,
                idempotency_key=f"scheduled-continuation:{anchor.anchor_id}:delivery",
                metadata={
                    "anchor_id": anchor.anchor_id,
                    "instruction_authority": "none",
                    "provenance": "scheduled-result",
                    "result_digest": anchor.result_digest,
                    "run_id": anchor.run_id,
                },
            ),
            allocate_index=True,
        )


__all__ = ["ScheduledContinuationDeliveryCoordinator", "ScheduledOutboundDelivery"]
