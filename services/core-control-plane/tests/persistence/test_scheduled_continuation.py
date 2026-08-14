from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fdai.core.scheduler.continuation import (
    ContinuationAccess,
    ContinuationAuditKind,
    InMemoryContinuationAuditSink,
    ScheduledContinuationService,
)
from fdai.delivery.persistence.postgres_scheduled_continuation import (
    PostgresScheduledContinuationStoreConfig,
    PostgresScheduledConversationAnchorStore,
    _row_to_anchor,
    _values,
)
from fdai.shared.providers.scheduled_continuation import (
    ContinuationAnchorState,
    ContinuationMode,
    ScheduledConversationAnchor,
    ScheduledResultOrigin,
    anchor_id_for_run,
)

NOW = datetime(2026, 7, 20, 21, 0, tzinfo=UTC)


def _anchor(*, suffix: str = "") -> ScheduledConversationAnchor:
    run_id = f"run-{suffix or '1'}"
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
        ),
        result_digest="a" * 64,
        result_summary="Scheduled result",
        evidence_refs=("audit:1",),
        observation_started_at=NOW - timedelta(hours=1),
        observation_ended_at=NOW,
        created_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )


def test_anchor_row_codec_round_trips() -> None:
    anchor = _anchor()
    columns = (
        "anchor_id task_id run_id owner_principal_id scope_ref mode origin result_digest "
        "result_summary evidence_refs observation_started_at observation_ended_at created_at "
        "expires_at state"
    ).split()
    row = dict(zip(columns, _values(anchor), strict=True))

    assert _row_to_anchor(row) == anchor


class _BarrierAnchorStore:
    def __init__(self, store: PostgresScheduledConversationAnchorStore) -> None:
        self._store = store
        self._expiry_barrier = asyncio.Barrier(2)

    async def create(self, anchor: ScheduledConversationAnchor) -> ScheduledConversationAnchor:
        return await self._store.create(anchor)

    async def get(self, anchor_id: str) -> ScheduledConversationAnchor | None:
        return await self._store.get(anchor_id)

    async def expire(
        self,
        *,
        anchor_id: str,
        expected_state: ContinuationAnchorState,
    ) -> ScheduledConversationAnchor | None:
        await self._expiry_barrier.wait()
        return await self._store.expire(anchor_id=anchor_id, expected_state=expected_state)

    async def list_for_principal(
        self,
        *,
        principal_id: str,
        limit: int = 100,
    ) -> tuple[ScheduledConversationAnchor, ...]:
        return await self._store.list_for_principal(principal_id=principal_id, limit=limit)


@pytest.mark.skipif(not os.environ.get("FDAI_DATABASE_URL"), reason="FDAI_DATABASE_URL is unset")
async def test_postgres_anchor_store_is_idempotent_and_expires_with_cas() -> None:
    config = PostgresScheduledContinuationStoreConfig(dsn=os.environ["FDAI_DATABASE_URL"])
    store = PostgresScheduledConversationAnchorStore(config=config)
    anchor = _anchor(suffix=uuid4().hex[:8])
    audit = InMemoryContinuationAuditSink()
    service = ScheduledContinuationService(store=store, audit=audit)

    assert await service.create(anchor) == anchor
    assert await service.create(anchor) == anchor
    restarted = PostgresScheduledConversationAnchorStore(config=config)
    assert await restarted.get(anchor.anchor_id) == anchor
    assert anchor in await restarted.list_for_principal(principal_id=anchor.owner_principal_id)

    concurrent = ScheduledContinuationService(
        store=_BarrierAnchorStore(restarted),
        audit=audit,
    )
    access = ContinuationAccess(principal_id=anchor.owner_principal_id)
    first, second = await asyncio.gather(
        concurrent.expire(anchor_id=anchor.anchor_id, access=access, now=NOW),
        concurrent.expire(anchor_id=anchor.anchor_id, access=access, now=NOW),
    )

    assert first.state is ContinuationAnchorState.EXPIRED
    assert second.state is ContinuationAnchorState.EXPIRED
    assert (await restarted.get(anchor.anchor_id)).state is ContinuationAnchorState.EXPIRED  # type: ignore[union-attr]
    assert [event.kind for event in audit.events].count(ContinuationAuditKind.CREATED) == 1
    assert [event.kind for event in audit.events].count(ContinuationAuditKind.CONTINUED) == 1
    assert [event.kind for event in audit.events].count(ContinuationAuditKind.EXPIRED) == 1
