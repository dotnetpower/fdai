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
    MAX_FENCE_ALIASES,
    MAX_FENCE_MIGRATION_BATCH,
    RETENTION_ORDER,
    ContinuationDeletionFence,
    ContinuationFenceMigrator,
    FenceCarryForward,
    InMemoryContinuationDeletionFence,
    InMemoryLegalHoldRegistry,
    InMemoryRetentionAuditSink,
    LegacyAliasDeletionFence,
    RetentionFenceUnavailableError,
    RetentionHoldUnavailableError,
    RetentionNotExpiredError,
    RetentionOutcome,
    RetentionTarget,
    ScheduledContinuationRetentionWorker,
    StateStoreContinuationDeletionFence,
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
    fence: ContinuationDeletionFence | None = None,
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
        fence=fence or InMemoryContinuationDeletionFence(),
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
        fence=InMemoryContinuationDeletionFence(),
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
            fence=InMemoryContinuationDeletionFence(),
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
        fence=StateStoreContinuationDeletionFence(store=state_store),
        grace=GRACE,
    )

    await worker.purge(anchor_id=anchor.anchor_id, now=DUE)
    await worker.purge(anchor_id=anchor.anchor_id, now=DUE)

    purge_entries = [
        entry
        for entry in state_store.audit_entries
        if entry["entry"].get("event_type") == "scheduled_continuation.retention.purged"
    ]
    fence_entries = [
        entry
        for entry in state_store.audit_entries
        if entry["entry"].get("event_type") == "scheduled_continuation.retention.fenced"
    ]
    assert len(purge_entries) == 1
    assert len(fence_entries) == 1
    assert anchor.result_summary not in str(state_store.audit_entries)


async def test_fence_is_recorded_before_the_first_deletion() -> None:
    anchor = _anchor()
    fence = InMemoryContinuationDeletionFence()
    observed: list[bool] = []

    class _FenceObservingDeleter(_RecordingDeleter):
        async def delete(
            self, *, target: RetentionTarget, anchor: ScheduledConversationAnchor
        ) -> None:
            observed.append(await fence.is_fenced(anchor_id=anchor.anchor_id))
            await super().delete(target=target, anchor=anchor)

    worker, _, _ = await _worker(anchor=anchor, deleter=_FenceObservingDeleter(), fence=fence)

    result = await worker.purge(anchor_id=anchor.anchor_id, now=DUE)

    assert result.outcome is RetentionOutcome.PURGED
    assert observed == [True, True, True]


async def test_partial_failure_keeps_the_fence_recorded() -> None:
    anchor = _anchor()
    fence = InMemoryContinuationDeletionFence()
    deleter = _RecordingDeleter(fail_on=RetentionTarget.ANCHOR)
    worker, _, _ = await _worker(anchor=anchor, deleter=deleter, fence=fence)

    result = await worker.purge(anchor_id=anchor.anchor_id, now=DUE)

    assert result.outcome is RetentionOutcome.PARTIAL
    assert await fence.is_fenced(anchor_id=anchor.anchor_id) is True


async def test_held_and_not_due_anchors_are_never_fenced() -> None:
    anchor = _anchor()
    held_fence = InMemoryContinuationDeletionFence()
    worker, _, _ = await _worker(
        anchor=anchor,
        holds=InMemoryLegalHoldRegistry([anchor.anchor_id]),
        fence=held_fence,
    )

    assert (await worker.purge(anchor_id=anchor.anchor_id, now=DUE)).outcome is (
        RetentionOutcome.HELD
    )
    assert await held_fence.is_fenced(anchor_id=anchor.anchor_id) is False

    early_fence = InMemoryContinuationDeletionFence()
    early_worker, _, _ = await _worker(anchor=anchor, fence=early_fence)

    assert (
        await early_worker.purge(anchor_id=anchor.anchor_id, now=DUE - timedelta(seconds=1))
    ).outcome is RetentionOutcome.NOT_DUE
    assert await early_fence.is_fenced(anchor_id=anchor.anchor_id) is False


async def test_unwritable_fence_fails_closed_before_any_deletion() -> None:
    anchor = _anchor()

    class _BrokenFence:
        async def record(self, *, anchor_id: str, at: datetime) -> None:
            del anchor_id, at
            raise ConnectionError("fence store unreachable")

        async def is_fenced(self, *, anchor_id: str) -> bool:
            del anchor_id
            return False

    worker, deleter, audit = await _worker(anchor=anchor, fence=_BrokenFence())

    with pytest.raises(RetentionFenceUnavailableError):
        await worker.purge(anchor_id=anchor.anchor_id, now=DUE)

    assert deleter.calls == []
    assert audit.events == []


async def test_state_store_fence_survives_a_restart_read() -> None:
    anchor = _anchor()
    state_store = InMemoryStateStore()
    fence = StateStoreContinuationDeletionFence(store=state_store)
    worker, _, _ = await _worker(anchor=anchor, fence=fence)

    await worker.purge(anchor_id=anchor.anchor_id, now=DUE)
    restarted = StateStoreContinuationDeletionFence(store=state_store)

    assert await restarted.is_fenced(anchor_id=anchor.anchor_id) is True
    assert await restarted.is_fenced(anchor_id="scheduled-anchor-other") is False


async def test_durable_fence_retry_resumes_a_partial_purge() -> None:
    anchor = _anchor()
    store = InMemoryScheduledConversationAnchorStore()
    await store.create(anchor)
    state_store = InMemoryStateStore()
    fence = StateStoreContinuationDeletionFence(store=state_store)
    failing = _RecordingDeleter(fail_on=RetentionTarget.SOURCE_RESULT)
    audit = InMemoryRetentionAuditSink()

    def build(deleter: _RecordingDeleter) -> ScheduledContinuationRetentionWorker:
        return ScheduledContinuationRetentionWorker(
            store=store,
            holds=InMemoryLegalHoldRegistry(),
            deleter=deleter,
            audit=audit,
            fence=fence,
            grace=GRACE,
        )

    first = await build(failing).purge(anchor_id=anchor.anchor_id, now=DUE)
    assert first.outcome is RetentionOutcome.PARTIAL

    healthy = _RecordingDeleter()
    second = await build(healthy).purge(anchor_id=anchor.anchor_id, now=DUE)

    assert second.outcome is RetentionOutcome.PURGED
    assert healthy.calls == list(RETENTION_ORDER)
    assert await fence.is_fenced(anchor_id=anchor.anchor_id) is True
    fenced = [
        entry
        for entry in state_store.audit_entries
        if entry["entry"]["event_type"] == "scheduled_continuation.retention.fenced"
    ]
    assert len(fenced) == 1


async def test_silently_dropped_fence_write_blocks_every_deletion() -> None:
    class _DroppingFence:
        async def record(self, *, anchor_id: str, at: datetime) -> None:
            del anchor_id, at

        async def is_fenced(self, *, anchor_id: str) -> bool:
            del anchor_id
            return False

    anchor = _anchor()
    worker, deleter, audit = await _worker(anchor=anchor, fence=_DroppingFence())

    with pytest.raises(RetentionFenceUnavailableError, match="readback"):
        await worker.purge(anchor_id=anchor.anchor_id, now=DUE)
    assert deleter.calls == []
    assert audit.events == []


LEGACY_ANCHOR_ID = "scheduled-anchor-legacy-derivation"
CURRENT_ANCHOR_ID = anchor_id_for_run(task_id="task-1", run_id="run-1")


class _UnreadableFence:
    async def record(self, *, anchor_id: str, at: datetime) -> None:
        del anchor_id, at
        raise ConnectionError("fence store unreachable")

    async def is_fenced(self, *, anchor_id: str) -> bool:
        del anchor_id
        raise ConnectionError("fence store unreachable")


class _UnwritableFence(InMemoryContinuationDeletionFence):
    async def record(self, *, anchor_id: str, at: datetime) -> None:
        del anchor_id, at
        raise ConnectionError("fence store is read-only")


class _DroppedWriteFence(InMemoryContinuationDeletionFence):
    """Accept the write and silently drop it, so the readback MUST keep work pending."""

    async def record(self, *, anchor_id: str, at: datetime) -> None:
        del anchor_id, at


def _migrator(fence: ContinuationDeletionFence) -> ContinuationFenceMigrator:
    return ContinuationFenceMigrator(fence=fence)


async def test_legacy_tombstone_refuses_a_recreated_id_before_migration() -> None:
    inner = InMemoryContinuationDeletionFence((LEGACY_ANCHOR_ID,))
    fence = LegacyAliasDeletionFence(fence=inner, aliases={CURRENT_ANCHOR_ID: (LEGACY_ANCHOR_ID,)})

    assert await fence.is_fenced(anchor_id=CURRENT_ANCHOR_ID) is True
    assert await fence.is_fenced(anchor_id="scheduled-anchor-unrelated") is False


async def test_alias_fence_writes_only_the_current_derivation() -> None:
    inner = InMemoryContinuationDeletionFence()
    fence = LegacyAliasDeletionFence(fence=inner, aliases={CURRENT_ANCHOR_ID: (LEGACY_ANCHOR_ID,)})

    await fence.record(anchor_id=CURRENT_ANCHOR_ID, at=NOW)

    assert await inner.is_fenced(anchor_id=CURRENT_ANCHOR_ID) is True
    assert await inner.is_fenced(anchor_id=LEGACY_ANCHOR_ID) is False


def test_alias_fence_rejects_unbounded_or_self_referential_aliases() -> None:
    inner = InMemoryContinuationDeletionFence()

    with pytest.raises(ValueError, match="MUST NOT exceed"):
        LegacyAliasDeletionFence(
            fence=inner,
            aliases={CURRENT_ANCHOR_ID: tuple(f"legacy-{i}" for i in range(MAX_FENCE_ALIASES + 1))},
        )
    with pytest.raises(ValueError, match="MUST differ"):
        LegacyAliasDeletionFence(fence=inner, aliases={CURRENT_ANCHOR_ID: (CURRENT_ANCHOR_ID,)})
    with pytest.raises(ValueError, match="bounded identifier"):
        LegacyAliasDeletionFence(fence=inner, aliases={CURRENT_ANCHOR_ID: ("  ",)})
    with pytest.raises(ValueError, match="only one current"):
        LegacyAliasDeletionFence(
            fence=inner,
            aliases={
                CURRENT_ANCHOR_ID: (LEGACY_ANCHOR_ID,),
                "other-current": (LEGACY_ANCHOR_ID,),
            },
        )
    with pytest.raises(ValueError, match="only one current"):
        LegacyAliasDeletionFence(
            fence=inner,
            aliases={
                CURRENT_ANCHOR_ID: (LEGACY_ANCHOR_ID,),
                LEGACY_ANCHOR_ID: ("older-anchor",),
            },
        )


async def test_migration_carries_the_tombstone_forward_and_keeps_the_legacy_key() -> None:
    fence = InMemoryContinuationDeletionFence((LEGACY_ANCHOR_ID,))
    pair = FenceCarryForward(legacy_anchor_id=LEGACY_ANCHOR_ID, current_anchor_id=CURRENT_ANCHOR_ID)

    result = await _migrator(fence).migrate(pairs=(pair,), now=NOW)

    assert result.carried == (CURRENT_ANCHOR_ID,)
    assert result.complete is True
    assert await fence.is_fenced(anchor_id=CURRENT_ANCHOR_ID) is True
    assert await fence.is_fenced(anchor_id=LEGACY_ANCHOR_ID) is True


async def test_migration_checks_direct_key_even_when_alias_reports_fenced() -> None:
    raw = InMemoryContinuationDeletionFence((LEGACY_ANCHOR_ID,))
    alias = LegacyAliasDeletionFence(fence=raw, aliases={CURRENT_ANCHOR_ID: (LEGACY_ANCHOR_ID,)})
    pair = FenceCarryForward(legacy_anchor_id=LEGACY_ANCHOR_ID, current_anchor_id=CURRENT_ANCHOR_ID)

    assert await alias.is_fenced(anchor_id=CURRENT_ANCHOR_ID) is True
    result = await _migrator(alias).migrate(pairs=(pair,), now=NOW)

    assert result.carried == (CURRENT_ANCHOR_ID,)
    assert result.already_present == ()
    assert await raw.is_fenced(anchor_id=CURRENT_ANCHOR_ID) is True


async def test_migration_is_idempotent_and_resumable() -> None:
    fence = InMemoryContinuationDeletionFence((LEGACY_ANCHOR_ID,))
    pair = FenceCarryForward(legacy_anchor_id=LEGACY_ANCHOR_ID, current_anchor_id=CURRENT_ANCHOR_ID)
    migrator = _migrator(fence)

    await migrator.migrate(pairs=(pair,), now=NOW)
    second = await migrator.migrate(pairs=(pair,), now=NOW + timedelta(hours=1))

    assert second.carried == ()
    assert second.already_present == (CURRENT_ANCHOR_ID,)


async def test_migration_skips_an_unfenced_legacy_id() -> None:
    fence = InMemoryContinuationDeletionFence()
    pair = FenceCarryForward(legacy_anchor_id=LEGACY_ANCHOR_ID, current_anchor_id=CURRENT_ANCHOR_ID)

    result = await _migrator(fence).migrate(pairs=(pair,), now=NOW)

    assert result.absent == (CURRENT_ANCHOR_ID,)
    assert await fence.is_fenced(anchor_id=CURRENT_ANCHOR_ID) is False


async def test_migration_keeps_a_dropped_write_pending() -> None:
    fence = _DroppedWriteFence((LEGACY_ANCHOR_ID,))
    pair = FenceCarryForward(legacy_anchor_id=LEGACY_ANCHOR_ID, current_anchor_id=CURRENT_ANCHOR_ID)

    result = await _migrator(fence).migrate(pairs=(pair,), now=NOW)

    assert result.pending == (CURRENT_ANCHOR_ID,)
    assert result.carried == ()
    assert result.complete is False


async def test_migration_fails_closed_on_an_unreadable_or_unwritable_fence() -> None:
    pair = FenceCarryForward(legacy_anchor_id=LEGACY_ANCHOR_ID, current_anchor_id=CURRENT_ANCHOR_ID)

    with pytest.raises(RetentionFenceUnavailableError):
        await _migrator(_UnreadableFence()).migrate(pairs=(pair,), now=NOW)
    with pytest.raises(RetentionFenceUnavailableError):
        await _migrator(_UnwritableFence((LEGACY_ANCHOR_ID,))).migrate(pairs=(pair,), now=NOW)


async def test_migration_bounds_the_batch_and_requires_an_aware_time() -> None:
    fence = InMemoryContinuationDeletionFence()
    pair = FenceCarryForward(legacy_anchor_id=LEGACY_ANCHOR_ID, current_anchor_id=CURRENT_ANCHOR_ID)
    oversized = tuple(
        FenceCarryForward(legacy_anchor_id=f"legacy-{i}", current_anchor_id=f"current-{i}")
        for i in range(MAX_FENCE_MIGRATION_BATCH + 1)
    )

    with pytest.raises(ValueError, match="MUST NOT exceed"):
        await _migrator(fence).migrate(pairs=oversized, now=NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        await _migrator(fence).migrate(pairs=(pair,), now=NOW.replace(tzinfo=None))


def test_carry_forward_rejects_a_single_derivation_pair() -> None:
    with pytest.raises(ValueError, match="cross two anchor id derivations"):
        FenceCarryForward(legacy_anchor_id=CURRENT_ANCHOR_ID, current_anchor_id=CURRENT_ANCHOR_ID)


async def test_migrated_tombstone_survives_restart_through_the_state_store() -> None:
    store = InMemoryStateStore()
    fence = StateStoreContinuationDeletionFence(store=store)
    await fence.record(anchor_id=LEGACY_ANCHOR_ID, at=NOW)
    pair = FenceCarryForward(legacy_anchor_id=LEGACY_ANCHOR_ID, current_anchor_id=CURRENT_ANCHOR_ID)

    await _migrator(fence).migrate(pairs=(pair,), now=NOW)
    restarted = StateStoreContinuationDeletionFence(store=store)

    assert await restarted.is_fenced(anchor_id=CURRENT_ANCHOR_ID) is True
