"""Durable Slack and Teams delivery for one already persisted scheduled result.

The coordinator never regenerates a briefing and never re-runs scheduled work. It replays
the persisted anchor: the stored result summary, digest, evidence, conversation reference,
and thread mode. The stable anchor id is the delivery origin, so a retry, a queue
redelivery, and a restart collapse onto one durable outbound record.

Deletion wins over delivery. When retention fenced the anchor id, or the anchor row is
gone, the coordinator refuses instead of restoring a deleted body from an in-flight copy.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fdai.core.scheduler.continuation_retention import (
    ContinuationDeletionFence,
    assert_not_fenced,
)
from fdai.shared.providers.conversation_channel import (
    MAX_TEXT_CHARS,
    ChannelThreadMode,
    ConversationChannelKind,
    OutboundResponse,
)
from fdai.shared.providers.conversation_delivery import (
    ConversationDeliveryStore,
    OutboundDeliveryRecord,
    new_delivery_record,
)
from fdai.shared.providers.scheduled_continuation import (
    ContinuationAnchorState,
    ContinuationMode,
    ScheduledConversationAnchor,
    ScheduledConversationAnchorStore,
)

CONTINUATION_DELIVERY_STATUS = "scheduled-result"
EXTERNAL_CHANNEL_KINDS: frozenset[ConversationChannelKind] = frozenset(
    {ConversationChannelKind.SLACK, ConversationChannelKind.TEAMS}
)
TRUNCATION_MARKER = "\n[truncated]"


class ScheduledContinuationDeliveryError(RuntimeError):
    """Base failure for external scheduled-result delivery."""


class ContinuationDeliveryUnavailableError(ScheduledContinuationDeliveryError):
    """The persisted result is absent or no longer deliverable."""


class UnsupportedContinuationChannelError(ScheduledContinuationDeliveryError):
    """Only Slack and Teams use the durable external ledger."""


class ContinuationRenderingError(ScheduledContinuationDeliveryError):
    """The persisted anchor exceeds a channel envelope bound that MUST NOT be rewritten."""


class ContinuationDeliveryConflictError(ScheduledContinuationDeliveryError):
    """The same anchor origin was submitted with different persisted content."""


class ScheduledContinuationDeliveryCoordinator:
    """Submit one persisted scheduled result to the durable outbound reply ledger."""

    def __init__(
        self,
        *,
        anchors: ScheduledConversationAnchorStore,
        deliveries: ConversationDeliveryStore,
        fence: ContinuationDeletionFence,
        freshness: timedelta = timedelta(hours=6),
        retention: timedelta = timedelta(days=7),
    ) -> None:
        if freshness <= timedelta(0) or retention < freshness:
            raise ValueError("continuation delivery freshness and retention are invalid")
        self._anchors = anchors
        self._deliveries = deliveries
        self._fence = fence
        self._freshness = freshness
        self._retention = retention

    async def submit(self, *, anchor_id: str, now: datetime) -> OutboundDeliveryRecord:
        """Persist one durable outbound record for the stored scheduled result.

        Reads the anchor again instead of trusting a caller-held copy, so a deletion that
        landed between scheduling and delivery is observed. Raises
        `ContinuationDeletionFencedError` for a fenced anchor id,
        `ContinuationDeliveryUnavailableError` for a missing or expired anchor,
        `UnsupportedContinuationChannelError` for a non-external channel,
        `ContinuationRenderingError` for an identifier that exceeds the channel envelope,
        and `ContinuationDeliveryConflictError` when the same origin carries other content.
        Submitting the same anchor twice returns the existing record.
        """
        if now.tzinfo is None:
            raise ValueError("now MUST be timezone-aware")
        await assert_not_fenced(self._fence, anchor_id=anchor_id)
        anchor = await self._anchors.get(anchor_id)
        if anchor is None:
            raise ContinuationDeliveryUnavailableError(
                "scheduled continuation result is unavailable"
            )
        if anchor.state is not ContinuationAnchorState.ACTIVE or now >= anchor.expires_at:
            raise ContinuationDeliveryUnavailableError(
                "expired scheduled continuation is never delivered"
            )
        response = continuation_outbound_response(anchor)
        record = new_delivery_record(
            origin_ref=anchor.anchor_id,
            principal_id=anchor.owner_principal_id,
            scope_ref=anchor.scope_ref,
            conversation_id=anchor.origin.conversation_ref,
            binding_id=None,
            response=response,
            created_at=now,
            freshness=self._freshness,
            retention=self._retention,
        )
        try:
            return await self._deliveries.put(record)
        except ValueError as error:
            raise ContinuationDeliveryConflictError(
                "scheduled continuation origin already carries different content"
            ) from error


def continuation_outbound_response(anchor: ScheduledConversationAnchor) -> OutboundResponse:
    """Render the persisted result as channel-neutral data with no instruction authority.

    The anchor summary cap is larger than the channel text cap, so an oversized summary is
    truncated deterministically and flagged instead of failing delivery. Identifiers are
    never rewritten, because the anchor id carries delivery identity: an identifier that
    exceeds the channel envelope raises `ContinuationRenderingError`.
    """
    channel_kind = _external_channel_kind(anchor.origin.channel_kind)
    dedicated = anchor.mode is ContinuationMode.DEDICATED_THREAD
    text, truncated = _bounded_text(anchor.result_summary)
    try:
        return OutboundResponse(
            channel_kind=channel_kind,
            channel_id=anchor.origin.channel_ref,
            in_reply_to=anchor.anchor_id,
            thread_id=None if dedicated else anchor.origin.thread_ref,
            status=CONTINUATION_DELIVERY_STATUS,
            text=text,
            data={
                "anchor_id": anchor.anchor_id,
                "instruction_authority": "none",
                "observation_ended_at": anchor.observation_ended_at.isoformat(),
                "observation_started_at": anchor.observation_started_at.isoformat(),
                "provenance": "scheduled-result",
                "result_digest": anchor.result_digest,
                "result_truncated": truncated,
                "run_id": anchor.run_id,
            },
            evidence_refs=anchor.evidence_refs,
            thread_mode=ChannelThreadMode.DEDICATED if dedicated else ChannelThreadMode.ORIGIN,
        )
    except ValueError as error:
        raise ContinuationRenderingError(
            "scheduled continuation anchor exceeds a channel envelope bound"
        ) from error


def _bounded_text(summary: str) -> tuple[str, bool]:
    """Return channel-safe text plus whether the stored summary was truncated."""
    if len(summary) <= MAX_TEXT_CHARS:
        return summary, False
    return summary[: MAX_TEXT_CHARS - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER, True


def _external_channel_kind(value: str) -> ConversationChannelKind:
    try:
        kind = ConversationChannelKind(value)
    except ValueError as error:
        raise UnsupportedContinuationChannelError(
            "scheduled continuation origin has an unknown channel kind"
        ) from error
    if kind not in EXTERNAL_CHANNEL_KINDS:
        raise UnsupportedContinuationChannelError(
            "only Slack and Teams use the durable external continuation ledger"
        )
    return kind


__all__ = [
    "CONTINUATION_DELIVERY_STATUS",
    "EXTERNAL_CHANNEL_KINDS",
    "TRUNCATION_MARKER",
    "ContinuationDeliveryConflictError",
    "ContinuationDeliveryUnavailableError",
    "ContinuationRenderingError",
    "ScheduledContinuationDeliveryCoordinator",
    "ScheduledContinuationDeliveryError",
    "UnsupportedContinuationChannelError",
    "continuation_outbound_response",
]
