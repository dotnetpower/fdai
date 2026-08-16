from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.scheduler.continuation import (
    ContinuationAnchorState,
    ContinuationAudience,
    ContinuationMode,
    InMemoryScheduledConversationAnchorStore,
    ScheduledConversationAnchor,
    ScheduledResultOrigin,
    anchor_id_for_run,
)
from fdai.core.scheduler.continuation_retention import (
    RETENTION_ORDER,
    InMemoryLegalHoldRegistry,
    InMemoryRetentionAuditSink,
    RetentionHoldUnavailableError,
    RetentionNotExpiredError,
    RetentionOutcome,
    RetentionTarget,
    ScheduledContinuationRetentionWorker,
    StateStoreRetentionAuditSink,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)
GRACE = timedelta(days=30)
DUE = NOW + timedelta(days=7) + GRACE


def _anchor(*, run_id: str = "run-1") -> ScheduledConversationAnchor:
    return ScheduledConversationAnchor(
        anchor_id=anchor_id_for_run(task_id="task-1", run_id=run_id),
        task_id="task-1",
        run_id=run_id,
        owner_principal_id="principal-a",
        scope_ref="scope-a",
        mode=ContinuationMode.ORIGIN_THREAD,
        origin=ScheduledResultOrigin(
            channel_kind="web",
            channel_ref="console",
            conversation_ref="conversation-1",
            thread_ref="thread-1",
            audience=ContinuationAudience.DIRECT,
        ),
        result_digest="a" * 64,
        result_summary="No critical issues were found.",
        evidence_refs=("audit:1",),
        observation_started_at=NOW - timedelta(hours=1),
        observation_ended_at=NOW,
        created_at=NOW,
        expires_at=NOW + timedelta(days=7),
        state=ContinuationAnchorState.EXPIRED,
    )


class _RecordingDeleter:
    def __init__(self, *, fail_on: RetentionTarget | None = None) -> None:
        self.calls: list[RetentionTarget] = []
        self._fail_on = fail_on

    async def delete(self, *, target: RetentionTarget, anchor: ScheduledConversationAnchor) -> None:
        del anchor
        if target is self._fail_on:
            raise RuntimeError("storage unavailable")
        self.calls.append(target)


class _BrokenHoldRegistry:
    async def is_held(self, *, anchor_id: str) -> bool:
        del anchor_id
        raise ConnectionError("hold registry unreachable")


async def _worker(
    *,
    anchor: ScheduledConversationAnchor | None,
    deleter: _RecordingDeleter | None = None,
    holds: object | None = None,
    audit: InMemoryRetentionAuditSink | None = None,
) -> tuple[ScheduledContinuationRetentionWorker, _RecordingDeleter, InMemoryRetentionAuditSink]:
    store = InMemoryScheduledConversationAnchorStore()
    if anchor is not None:
        await store.create(anchor)
    used_deleter = deleter or _RecordingDeleter()
    used_audit = audit or InMemoryRetentionAuditSink()
    worker = ScheduledContinuationRetentionWorker(
        store=store,
        holds=holds or InMemoryLegalHoldRegistry(),
        deleter=used_deleter,
        audit=used_audit,
        grace=GRACE,
    )
    return worker, used_deleter, used_audit


async def test_due_anchor_is_deleted_in_declared_order() -> None:
    anchor = _anchor()
    worker, deleter, audit = await _worker(anchor=anchor)

    result = await worker.purge(anchor_id=anchor.anchor_id, now=DUE)

    assert result.outcome is RetentionOutcome.PURGED
    assert result.deleted is True
    assert tuple(deleter.calls) == RETENTION_ORDER
    assert deleter.calls[-1] is RetentionTarget.ANCHOR
    assert [event.outcome for event in audit.events] == [RetentionOutcome.PURGED]


async def test_active_anchor_is_never_deleted() -> None:
    anchor = replace(_anchor(), state=ContinuationAnchorState.ACTIVE)
    worker, deleter, audit = await _worker(anchor=anchor)

    with pytest.raises(RetentionNotExpiredError):
        await worker.purge(anchor_id=anchor.anchor_id, now=DUE)

    assert deleter.calls == []
    assert audit.events == []


async def test_legal_hold_blocks_deletion_and_is_audited() -> None:
    anchor = _anchor()
    holds = InMemoryLegalHoldRegistry([anchor.anchor_id])
    worker, deleter, audit = await _worker(anchor=anchor, holds=holds)

    result = await worker.purge(anchor_id=anchor.anchor_id, now=DUE)

    assert result.outcome is RetentionOutcome.HELD
    assert result.deleted is False
    assert deleter.calls == []
    assert [event.outcome for event in audit.events] == [RetentionOutcome.HELD]


async def test_released_hold_allows_a_later_purge() -> None:
    anchor = _anchor()
    holds = InMemoryLegalHoldRegistry([anchor.anchor_id])
    worker, deleter, _ = await _worker(anchor=anchor, holds=holds)

    assert (await worker.purge(anchor_id=anchor.anchor_id, now=DUE)).outcome is (
        RetentionOutcome.HELD
    )
    holds.release_hold(anchor.anchor_id)

    assert (await worker.purge(anchor_id=anchor.anchor_id, now=DUE)).outcome is (
        RetentionOutcome.PURGED
    )
    assert tuple(deleter.calls) == RETENTION_ORDER


async def test_unreadable_hold_registry_fails_closed() -> None:
    anchor = _anchor()
    worker, deleter, audit = await _worker(anchor=anchor, holds=_BrokenHoldRegistry())

    with pytest.raises(RetentionHoldUnavailableError):
        await worker.purge(anchor_id=anchor.anchor_id, now=DUE)

    assert deleter.calls == []
    assert audit.events == []


async def test_anchor_inside_the_grace_window_is_not_due() -> None:
    anchor = _anchor()
    worker, deleter, audit = await _worker(anchor=anchor)

    result = await worker.purge(anchor_id=anchor.anchor_id, now=DUE - timedelta(seconds=1))

    assert result.outcome is RetentionOutcome.NOT_DUE
    assert deleter.calls == []
    assert [event.outcome for event in audit.events] == [RetentionOutcome.NOT_DUE]


async def test_partial_failure_keeps_the_anchor_and_reports_the_failed_target() -> None:
    anchor = _anchor()
    deleter = _RecordingDeleter(fail_on=RetentionTarget.SOURCE_RESULT)
    worker, _, audit = await _worker(anchor=anchor, deleter=deleter)

    result = await worker.purge(anchor_id=anchor.anchor_id, now=DUE)

    assert result.outcome is RetentionOutcome.PARTIAL
    assert result.deleted is False
    assert result.failed_target is RetentionTarget.SOURCE_RESULT
    assert result.completed_targets == (RetentionTarget.PROJECTED_TURN,)
    assert RetentionTarget.ANCHOR not in deleter.calls
    assert [event.outcome for event in audit.events] == [RetentionOutcome.PARTIAL]


async def test_repeated_partial_failure_collapses_onto_one_audit_record() -> None:
    anchor = _anchor()
    audit = InMemoryRetentionAuditSink()
    failing = _RecordingDeleter(fail_on=RetentionTarget.ANCHOR)
    store = InMemoryScheduledConversationAnchorStore()
    await store.create(anchor)
    worker = ScheduledContinuationRetentionWorker(
        store=store,
        holds=InMemoryLegalHoldRegistry(),
        deleter=failing,
        audit=audit,
        grace=GRACE,
    )

    first = await worker.purge(anchor_id=anchor.anchor_id, now=DUE)
    second = await worker.purge(anchor_id=anchor.anchor_id, now=DUE)

    assert first.outcome is RetentionOutcome.PARTIAL
    assert second.outcome is RetentionOutcome.PARTIAL
    assert [event.outcome for event in audit.events] == [RetentionOutcome.PARTIAL]


async def test_missing_anchor_is_an_idempotent_no_op() -> None:
    worker, deleter, audit = await _worker(anchor=None)

    result = await worker.purge(anchor_id="scheduled-anchor-missing", now=DUE)

    assert result.outcome is RetentionOutcome.PURGED
    assert deleter.calls == []
    assert audit.events == []


async def test_naive_now_is_rejected() -> None:
    anchor = _anchor()
    worker, _, _ = await _worker(anchor=anchor)

    with pytest.raises(ValueError, match="timezone-aware"):
        await worker.purge(anchor_id=anchor.anchor_id, now=DUE.replace(tzinfo=None))


async def test_batch_is_bounded() -> None:
    worker, _, _ = await _worker(anchor=None)

    with pytest.raises(ValueError, match="MUST NOT exceed"):
        await worker.purge_batch(anchor_ids=[f"anchor-{index}" for index in range(101)], now=DUE)


async def test_negative_grace_is_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        ScheduledContinuationRetentionWorker(
            store=InMemoryScheduledConversationAnchorStore(),
            holds=InMemoryLegalHoldRegistry(),
            deleter=_RecordingDeleter(),
            audit=InMemoryRetentionAuditSink(),
            grace=timedelta(seconds=-1),
        )


async def test_state_store_audit_sink_collapses_retries_without_result_text() -> None:
    anchor = _anchor()
    state_store = InMemoryStateStore()
    anchor_store = InMemoryScheduledConversationAnchorStore()
    await anchor_store.create(anchor)
    worker = ScheduledContinuationRetentionWorker(
        store=anchor_store,
        holds=InMemoryLegalHoldRegistry(),
        deleter=_RecordingDeleter(),
        audit=StateStoreRetentionAuditSink(store=state_store),
        grace=GRACE,
    )

    await worker.purge(anchor_id=anchor.anchor_id, now=DUE)
    await worker.purge(anchor_id=anchor.anchor_id, now=DUE)

    entries = [entry for entry in state_store.audit_entries if "retention" in str(entry)]
    assert len(entries) == 1
    assert anchor.result_summary not in str(entries[0])
