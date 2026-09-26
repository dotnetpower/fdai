from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fdai.core.scheduler.continuation_retention import (
    RETENTION_ORDER,
    InMemoryContinuationDeletionFence,
    InMemoryLegalHoldRegistry,
    InMemoryRetentionAuditSink,
    RetentionOutcome,
    RetentionTarget,
    ScheduledContinuationRetentionWorker,
)
from fdai.delivery.persistence.postgres_scheduled_continuation import (
    PostgresScheduledContinuationStoreConfig,
    PostgresScheduledConversationAnchorStore,
    psycopg_dsn,
)
from fdai.delivery.persistence.postgres_scheduled_continuation_retention import (
    PostgresScheduledContinuationDeleter,
    RetentionReadbackError,
    retention_statement,
)
from fdai.shared.providers.scheduled_continuation import (
    ContinuationAnchorState,
    ContinuationMode,
    ScheduledConversationAnchor,
    ScheduledResultOrigin,
    anchor_id_for_run,
    projected_turn_id_for_anchor,
)

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


def test_projected_turn_statement_is_scoped_to_the_owner_and_conversation() -> None:
    anchor = _anchor()

    statement = retention_statement(target=RetentionTarget.PROJECTED_TURN, anchor=anchor)

    assert statement.delete_sql.startswith("DELETE FROM conversation_turn")
    assert "principal_id = %s" in statement.delete_sql
    assert "conversation_id = %s" in statement.delete_sql
    assert statement.params == (
        anchor.owner_principal_id,
        anchor.origin.conversation_ref,
        projected_turn_id_for_anchor(anchor.anchor_id),
        anchor.anchor_id,
    )
    assert statement.readback_sql.startswith("SELECT 1 FROM conversation_turn")
    assert statement.readback_sql.endswith("LIMIT 1")


def test_source_result_statement_targets_the_exact_run() -> None:
    anchor = _anchor()

    statement = retention_statement(target=RetentionTarget.SOURCE_RESULT, anchor=anchor)

    assert statement.delete_sql == (
        "DELETE FROM briefing_run WHERE principal_id = %s AND run_id = %s"
    )
    assert statement.params == (anchor.owner_principal_id, anchor.run_id)


def test_anchor_statement_refuses_a_reactivated_row() -> None:
    anchor = _anchor()

    statement = retention_statement(target=RetentionTarget.ANCHOR, anchor=anchor)

    assert statement.delete_sql.endswith("AND state = 'expired'")
    assert statement.params == (anchor.anchor_id,)
    assert "state" not in statement.readback_sql


def test_every_target_has_a_distinct_scoped_statement() -> None:
    anchor = _anchor()

    statements = [retention_statement(target=target, anchor=anchor) for target in RETENTION_ORDER]

    assert len({statement.delete_sql for statement in statements}) == len(RETENTION_ORDER)
    for statement in statements:
        assert "%s" in statement.delete_sql
        assert statement.delete_sql.count("%s") == len(statement.params)


def test_readback_params_match_the_delete_params() -> None:
    anchor = _anchor()

    for target in RETENTION_ORDER:
        statement = retention_statement(target=target, anchor=anchor)
        assert statement.readback_sql.count("%s") == len(statement.params)


@pytest.mark.skipif(not os.environ.get("FDAI_DATABASE_URL"), reason="FDAI_DATABASE_URL is unset")
async def test_live_purge_deletes_every_copy_and_preserves_unrelated_scopes() -> None:
    dsn = os.environ["FDAI_DATABASE_URL"]
    config = PostgresScheduledContinuationStoreConfig(dsn=dsn)
    store = PostgresScheduledConversationAnchorStore(config=config)
    suffix = uuid4().hex[:12]
    anchor = _anchor(run_id=f"run-{suffix}")
    other = _anchor(run_id=f"run-other-{suffix}")
    await store.create(anchor)
    await store.create(other)
    worker = ScheduledContinuationRetentionWorker(
        store=store,
        holds=InMemoryLegalHoldRegistry(),
        deleter=PostgresScheduledContinuationDeleter(config=config),
        audit=InMemoryRetentionAuditSink(),
        fence=InMemoryContinuationDeletionFence(),
        grace=GRACE,
    )

    try:
        result = await worker.purge(anchor_id=anchor.anchor_id, now=DUE)

        assert result.outcome is RetentionOutcome.PURGED
        assert await store.get(anchor.anchor_id) is None
        assert await store.get(other.anchor_id) is not None
    finally:
        async with await psycopg.AsyncConnection.connect(psycopg_dsn(dsn)) as connection:
            await connection.execute(
                "DELETE FROM scheduled_conversation_anchor WHERE anchor_id IN (%s, %s)",
                (anchor.anchor_id, other.anchor_id),
            )


@pytest.mark.skipif(not os.environ.get("FDAI_DATABASE_URL"), reason="FDAI_DATABASE_URL is unset")
async def test_live_readback_keeps_a_surviving_copy_pending() -> None:
    dsn = os.environ["FDAI_DATABASE_URL"]
    config = PostgresScheduledContinuationStoreConfig(dsn=dsn)
    store = PostgresScheduledConversationAnchorStore(config=config)
    suffix = uuid4().hex[:12]
    anchor = _anchor(run_id=f"run-active-{suffix}")
    active = replace(anchor, state=ContinuationAnchorState.ACTIVE)
    await store.create(active)
    deleter = PostgresScheduledContinuationDeleter(config=config)

    try:
        with pytest.raises(RetentionReadbackError):
            await deleter.delete(target=RetentionTarget.ANCHOR, anchor=anchor)
        assert await store.get(anchor.anchor_id) is not None
    finally:
        async with await psycopg.AsyncConnection.connect(psycopg_dsn(dsn)) as connection:
            await connection.execute(
                "DELETE FROM scheduled_conversation_anchor WHERE anchor_id = %s",
                (anchor.anchor_id,),
            )


def test_unsupported_target_is_refused_instead_of_planning_nothing() -> None:
    with pytest.raises(ValueError, match="unsupported scheduled continuation retention target"):
        retention_statement(target="legacy_cohort_copy", anchor=_anchor())  # type: ignore[arg-type]


def test_production_deleter_is_reachable_from_the_persistence_package() -> None:
    from fdai.delivery import persistence

    assert persistence.PostgresScheduledContinuationDeleter is PostgresScheduledContinuationDeleter
    assert persistence.RetentionReadbackError is RetentionReadbackError
