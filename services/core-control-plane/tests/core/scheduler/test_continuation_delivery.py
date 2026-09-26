from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.scheduler.continuation import InMemoryScheduledConversationAnchorStore
from fdai.core.scheduler.continuation_delivery import (
    CONTINUATION_DELIVERY_STATUS,
    TRUNCATION_MARKER,
    ContinuationDeliveryConflictError,
    ContinuationDeliveryUnavailableError,
    ContinuationRenderingError,
    ScheduledContinuationDeliveryCoordinator,
    UnsupportedContinuationChannelError,
    continuation_outbound_response,
)
from fdai.core.scheduler.continuation_retention import (
    ContinuationDeletionFencedError,
    InMemoryContinuationDeletionFence,
    RetentionFenceUnavailableError,
)
from fdai.shared.providers.conversation_channel import (
    MAX_TEXT_CHARS,
    ChannelThreadMode,
    ConversationChannelKind,
)
from fdai.shared.providers.conversation_delivery import (
    InMemoryConversationDeliveryStore,
    OutboundDeliveryState,
)
from fdai.shared.providers.scheduled_continuation import (
    ContinuationAnchorState,
    ContinuationMode,
    ScheduledConversationAnchor,
    ScheduledResultOrigin,
    anchor_id_for_run,
)

NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)


def _anchor(
    *,
    run_id: str = "run-1",
    channel_kind: str = "slack",
    mode: ContinuationMode = ContinuationMode.ORIGIN_THREAD,
) -> ScheduledConversationAnchor:
    return ScheduledConversationAnchor(
        anchor_id=anchor_id_for_run(task_id="task-1", run_id=run_id),
        task_id="task-1",
        run_id=run_id,
        owner_principal_id="principal-a",
        scope_ref="scope-a",
        mode=mode,
        origin=ScheduledResultOrigin(
            channel_kind=channel_kind,
            channel_ref="channel-1",
            conversation_ref="conversation-1",
            thread_ref="thread-1",
        ),
        result_digest="a" * 64,
        result_summary="No critical issues were found.",
        evidence_refs=("audit:1",),
        observation_started_at=NOW - timedelta(hours=1),
        observation_ended_at=NOW,
        created_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )


class _RewritingAnchorStore(InMemoryScheduledConversationAnchorStore):
    """Return a rewritten body on the second read to model a late content change."""

    def __init__(
        self,
        *,
        first: ScheduledConversationAnchor,
        second: ScheduledConversationAnchor,
    ) -> None:
        super().__init__()
        self._reads = 0
        self._first = first
        self._second = second

    async def get(self, anchor_id: str) -> ScheduledConversationAnchor | None:
        del anchor_id
        self._reads += 1
        return self._first if self._reads == 1 else self._second


async def _coordinator(
    *,
    anchor: ScheduledConversationAnchor | None,
    fence: object | None = None,
) -> tuple[
    ScheduledContinuationDeliveryCoordinator,
    InMemoryScheduledConversationAnchorStore,
    InMemoryConversationDeliveryStore,
]:
    anchors = InMemoryScheduledConversationAnchorStore()
    if anchor is not None:
        await anchors.create(anchor)
    deliveries = InMemoryConversationDeliveryStore()
    coordinator = ScheduledContinuationDeliveryCoordinator(
        anchors=anchors,
        deliveries=deliveries,
        fence=fence or InMemoryContinuationDeletionFence(),
    )
    return coordinator, anchors, deliveries


async def test_persisted_result_is_submitted_with_the_anchor_id_as_origin() -> None:
    anchor = _anchor()
    coordinator, _, deliveries = await _coordinator(anchor=anchor)

    record = await coordinator.submit(anchor_id=anchor.anchor_id, now=NOW)

    assert record.state is OutboundDeliveryState.PENDING
    assert record.principal_id == anchor.owner_principal_id
    assert record.scope_ref == anchor.scope_ref
    assert record.conversation_id == anchor.origin.conversation_ref
    assert record.response.in_reply_to == anchor.anchor_id
    assert record.response.text == anchor.result_summary
    assert record.response.status == CONTINUATION_DELIVERY_STATUS
    assert record.response.data["instruction_authority"] == "none"
    assert record.response.data["result_digest"] == anchor.result_digest
    assert await deliveries.get(record.delivery_id) == record


async def test_replay_collapses_onto_one_durable_record() -> None:
    anchor = _anchor()
    coordinator, _, deliveries = await _coordinator(anchor=anchor)

    first = await coordinator.submit(anchor_id=anchor.anchor_id, now=NOW)
    second = await coordinator.submit(anchor_id=anchor.anchor_id, now=NOW + timedelta(minutes=5))

    assert first == second
    assert (await deliveries.snapshot()).deliveries == (first,)


async def test_teams_dedicated_thread_drops_the_origin_thread_reference() -> None:
    anchor = _anchor(channel_kind="teams", mode=ContinuationMode.DEDICATED_THREAD)
    coordinator, _, _ = await _coordinator(anchor=anchor)

    record = await coordinator.submit(anchor_id=anchor.anchor_id, now=NOW)

    assert record.response.channel_kind is ConversationChannelKind.TEAMS
    assert record.response.thread_mode is ChannelThreadMode.DEDICATED
    assert record.response.thread_id is None


async def test_slack_origin_thread_keeps_the_recorded_thread_reference() -> None:
    anchor = _anchor()

    response = continuation_outbound_response(anchor)

    assert response.channel_kind is ConversationChannelKind.SLACK
    assert response.thread_mode is ChannelThreadMode.ORIGIN
    assert response.thread_id == anchor.origin.thread_ref
    assert response.evidence_refs == anchor.evidence_refs


async def test_fenced_anchor_is_never_redelivered() -> None:
    anchor = _anchor()
    fence = InMemoryContinuationDeletionFence([anchor.anchor_id])
    coordinator, _, deliveries = await _coordinator(anchor=anchor, fence=fence)

    with pytest.raises(ContinuationDeletionFencedError):
        await coordinator.submit(anchor_id=anchor.anchor_id, now=NOW)

    assert (await deliveries.snapshot()).deliveries == ()


async def test_unreadable_fence_fails_closed() -> None:
    class _BrokenFence:
        async def record(self, *, anchor_id: str, at: datetime) -> None:
            del anchor_id, at
            raise ConnectionError("fence store unreachable")

        async def is_fenced(self, *, anchor_id: str) -> bool:
            del anchor_id
            raise ConnectionError("fence store unreachable")

    anchor = _anchor()
    coordinator, _, deliveries = await _coordinator(anchor=anchor, fence=_BrokenFence())

    with pytest.raises(RetentionFenceUnavailableError):
        await coordinator.submit(anchor_id=anchor.anchor_id, now=NOW)

    assert (await deliveries.snapshot()).deliveries == ()


async def test_deleted_result_is_not_regenerated() -> None:
    coordinator, _, deliveries = await _coordinator(anchor=None)

    with pytest.raises(ContinuationDeliveryUnavailableError):
        await coordinator.submit(anchor_id="scheduled-anchor-missing", now=NOW)

    assert (await deliveries.snapshot()).deliveries == ()


async def test_expired_anchor_is_not_delivered() -> None:
    anchor = replace(_anchor(), state=ContinuationAnchorState.EXPIRED)
    coordinator, _, _ = await _coordinator(anchor=anchor)

    with pytest.raises(ContinuationDeliveryUnavailableError):
        await coordinator.submit(anchor_id=anchor.anchor_id, now=NOW)


async def test_anchor_past_its_expiry_time_is_not_delivered() -> None:
    anchor = _anchor()
    coordinator, _, _ = await _coordinator(anchor=anchor)

    with pytest.raises(ContinuationDeliveryUnavailableError):
        await coordinator.submit(anchor_id=anchor.anchor_id, now=anchor.expires_at)


async def test_web_origin_uses_the_conversation_path_not_the_external_ledger() -> None:
    anchor = _anchor(channel_kind="web")
    coordinator, _, _ = await _coordinator(anchor=anchor)

    with pytest.raises(UnsupportedContinuationChannelError):
        await coordinator.submit(anchor_id=anchor.anchor_id, now=NOW)


async def test_unknown_channel_kind_is_refused() -> None:
    anchor = _anchor(channel_kind="pager")
    coordinator, _, _ = await _coordinator(anchor=anchor)

    with pytest.raises(UnsupportedContinuationChannelError):
        await coordinator.submit(anchor_id=anchor.anchor_id, now=NOW)


async def test_changed_persisted_content_on_the_same_origin_is_a_conflict() -> None:
    anchor = _anchor()
    rewritten = replace(anchor, result_summary="Rewritten summary.")
    coordinator = ScheduledContinuationDeliveryCoordinator(
        anchors=_RewritingAnchorStore(first=anchor, second=rewritten),
        deliveries=InMemoryConversationDeliveryStore(),
        fence=InMemoryContinuationDeletionFence(),
    )
    await coordinator.submit(anchor_id=anchor.anchor_id, now=NOW)

    with pytest.raises(ContinuationDeliveryConflictError):
        await coordinator.submit(anchor_id=anchor.anchor_id, now=NOW)


async def test_naive_now_is_rejected() -> None:
    anchor = _anchor()
    coordinator, _, _ = await _coordinator(anchor=anchor)

    with pytest.raises(ValueError, match="timezone-aware"):
        await coordinator.submit(anchor_id=anchor.anchor_id, now=NOW.replace(tzinfo=None))


def test_invalid_freshness_and_retention_are_rejected() -> None:
    with pytest.raises(ValueError, match="freshness and retention"):
        ScheduledContinuationDeliveryCoordinator(
            anchors=InMemoryScheduledConversationAnchorStore(),
            deliveries=InMemoryConversationDeliveryStore(),
            fence=InMemoryContinuationDeletionFence(),
            freshness=timedelta(days=2),
            retention=timedelta(days=1),
        )


def test_oversized_summary_is_truncated_and_flagged() -> None:
    anchor = replace(_anchor(), result_summary="s" * (MAX_TEXT_CHARS + 500))

    response = continuation_outbound_response(anchor)

    assert len(response.text) == MAX_TEXT_CHARS
    assert response.text.endswith(TRUNCATION_MARKER)
    assert response.data["result_truncated"] is True
    assert response.data["result_digest"] == anchor.result_digest


def test_bounded_summary_is_not_truncated() -> None:
    response = continuation_outbound_response(_anchor())

    assert response.data["result_truncated"] is False
    assert not response.text.endswith(TRUNCATION_MARKER)


async def test_oversized_identifier_is_refused_without_rewriting() -> None:
    anchor = _anchor()
    oversized = replace(anchor, origin=replace(anchor.origin, channel_ref="C" * 240))
    coordinator, anchors, _ = await _coordinator(anchor=oversized)

    with pytest.raises(ContinuationRenderingError):
        await coordinator.submit(anchor_id=oversized.anchor_id, now=NOW)
    assert await anchors.get(oversized.anchor_id) is not None
