from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.scheduler.continuation import (
    ContinuationAccess,
    ContinuationAccessDeniedError,
    ContinuationAudience,
    ContinuationAuditKind,
    ContinuationMode,
    InMemoryContinuationAuditSink,
    InMemoryScheduledConversationAnchorStore,
    ScheduledContinuationService,
    ScheduledConversationAnchor,
    ScheduledResultOrigin,
    anchor_id_for_run,
    scheduled_result_to_typed_fact,
)
from fdai.core.working_context.types import EntryKind

NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)


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
        ),
        result_digest="a" * 64,
        result_summary="No critical issues were found.",
        evidence_refs=("audit:1",),
        observation_started_at=NOW - timedelta(hours=1),
        observation_ended_at=NOW,
        created_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )


def _service() -> tuple[ScheduledContinuationService, InMemoryContinuationAuditSink]:
    audit = InMemoryContinuationAuditSink()
    return (
        ScheduledContinuationService(
            store=InMemoryScheduledConversationAnchorStore(),
            audit=audit,
        ),
        audit,
    )


async def test_owner_and_authorized_same_scope_can_resolve() -> None:
    service, audit = _service()
    anchor = await service.create(_anchor())

    assert (
        await service.resolve(
            anchor_id=anchor.anchor_id,
            access=ContinuationAccess(principal_id="principal-a"),
            now=NOW,
        )
        == anchor
    )
    assert (
        await service.resolve(
            anchor_id=anchor.anchor_id,
            access=ContinuationAccess(
                principal_id="principal-b",
                authorized_scope_refs=frozenset({"scope-a"}),
            ),
            now=NOW,
        )
        == anchor
    )
    assert [event.kind for event in audit.events] == [
        ContinuationAuditKind.CREATED,
        ContinuationAuditKind.CONTINUED,
        ContinuationAuditKind.CONTINUED,
    ]


@pytest.mark.parametrize("anchor_id", ["guessed-anchor", None])
async def test_cross_scope_and_guessed_anchor_have_same_denial(anchor_id: str | None) -> None:
    service, audit = _service()
    anchor = await service.create(_anchor())

    with pytest.raises(
        ContinuationAccessDeniedError,
        match="scheduled continuation is unavailable",
    ):
        await service.resolve(
            anchor_id=anchor_id or anchor.anchor_id,
            access=ContinuationAccess(principal_id="principal-b"),
            now=NOW,
        )
    assert audit.events[-1].kind is ContinuationAuditKind.ACCESS_DENIED


async def test_expired_anchor_denies_and_records_expiry() -> None:
    service, audit = _service()
    anchor = await service.create(_anchor())

    with pytest.raises(ContinuationAccessDeniedError):
        await service.resolve(
            anchor_id=anchor.anchor_id,
            access=ContinuationAccess(principal_id="principal-a"),
            now=anchor.expires_at,
        )
    assert [event.kind for event in audit.events[-2:]] == [
        ContinuationAuditKind.EXPIRED,
        ContinuationAuditKind.ACCESS_DENIED,
    ]


def test_broadcast_result_cannot_create_an_anchor() -> None:
    with pytest.raises(ValueError, match="broadcast"):
        replace(
            _anchor(),
            origin=replace(_anchor().origin, audience=ContinuationAudience.BROADCAST),
        )


async def test_each_recurring_run_gets_one_idempotent_distinct_anchor() -> None:
    store = InMemoryScheduledConversationAnchorStore()
    first = _anchor(run_id="run-1")
    second = _anchor(run_id="run-2")

    assert await store.create(first) == first
    assert await store.create(first) == first
    assert await store.create(second) == second
    assert first.anchor_id != second.anchor_id


async def test_store_lists_only_owner_anchors() -> None:
    store = InMemoryScheduledConversationAnchorStore()
    owner = _anchor(run_id="run-owner")
    other = replace(
        _anchor(run_id="run-other"),
        owner_principal_id="principal-b",
    )
    await store.create(owner)
    await store.create(other)

    assert await store.list_for_principal(principal_id="principal-a") == (owner,)


def test_projection_is_provenance_labeled_data_without_instruction_authority() -> None:
    entry = scheduled_result_to_typed_fact(_anchor(), token_estimator=len)

    assert entry.kind is EntryKind.TYPED_FACT
    assert entry.trusted is False
    assert entry.metadata["instruction_authority"] == "none"
    assert entry.metadata["result_digest"] == "a" * 64
    assert "run=run-1" in entry.text
    assert "window=" in entry.text
    assert "evidence=audit:1" in entry.text
