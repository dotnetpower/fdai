from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, call, sentinel

import pytest

from fdai.delivery.persistence.postgres_user_context import PostgresUserContextStoreConfig
from fdai.delivery.persistence.postgres_user_context_projection_queue import (
    enqueue_projection_upsert,
)
from fdai.delivery.persistence.postgres_user_context_projection_recovery import (
    PostgresUserContextProjectionRecovery,
    ProjectionUpsertJob,
    _turn_exchanges,
)
from fdai.shared.providers.user_context import (
    ConversationTurnRecord,
    ConversationTurnRole,
)

NOW = datetime(2026, 7, 16, 7, 0, tzinfo=UTC)


def _async_context(value: object) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=value)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


def _recovery_with_connection() -> tuple[PostgresUserContextProjectionRecovery, MagicMock]:
    connection = MagicMock()
    connection.__aenter__ = AsyncMock(return_value=connection)
    connection.__aexit__ = AsyncMock(return_value=None)
    connection.transaction.return_value = _async_context(connection)
    connection.execute = AsyncMock()
    recovery = PostgresUserContextProjectionRecovery(
        config=PostgresUserContextStoreConfig(dsn="postgresql://example"),
        projector=MagicMock(),
    )
    recovery._connect = AsyncMock(return_value=connection)  # type: ignore[method-assign]
    return recovery, connection


def _turn(
    turn_id: str,
    role: ConversationTurnRole,
    idempotency_key: str,
    turn_index: int,
) -> ConversationTurnRecord:
    return ConversationTurnRecord(
        turn_id=turn_id,
        conversation_id="conversation-1",
        principal_id="principal-1",
        turn_index=turn_index,
        role=role,
        content=f"body-{turn_id}",
        recorded_at=NOW,
        idempotency_key=idempotency_key,
    )


async def test_enqueue_projection_upsert_uses_source_reference_only() -> None:
    connection = AsyncMock()

    await enqueue_projection_upsert(
        connection,
        projection_kind="memory",
        principal_id="principal-1",
        record_id="memory-1",
    )

    query, parameters = connection.execute.await_args.args
    assert "user_context_projection_upsert_queue" in query
    assert "body" not in query
    assert parameters == ("memory", "principal-1", "memory-1")


def test_turn_exchanges_pair_only_matching_request_keys() -> None:
    operator = _turn("operator-1", ConversationTurnRole.OPERATOR, "request-1:operator", 0)
    unrelated = _turn("assistant-2", ConversationTurnRole.ASSISTANT, "request-2:assistant", 1)
    assistant = _turn("assistant-1", ConversationTurnRole.ASSISTANT, "request-1:assistant", 2)

    assert _turn_exchanges((operator, unrelated, assistant)) == ((operator, assistant),)


@pytest.mark.parametrize(
    ("projection_kind", "projector_method"),
    [
        ("preference", "project_preference"),
        ("memory", "project_memory"),
        ("policy", "project_policy"),
        ("briefing_subscription", "project_subscription"),
        ("briefing_run", "project_briefing_run"),
        ("workflow_definition", "project_workflow_definition"),
        ("workflow_binding", "project_workflow_binding"),
    ],
)
async def test_project_dispatches_source_record_to_ontology_projector(
    projection_kind: str,
    projector_method: str,
) -> None:
    projector = MagicMock()
    setattr(projector, projector_method, AsyncMock())
    recovery = PostgresUserContextProjectionRecovery(
        config=PostgresUserContextStoreConfig(dsn="postgresql://example"),
        projector=projector,
    )
    recovery._one = AsyncMock(return_value=sentinel.record)  # type: ignore[method-assign]
    job = ProjectionUpsertJob(projection_kind, "principal-1", "record-1", 0)

    assert await recovery.project(job) is True

    getattr(projector, projector_method).assert_awaited_once_with(sentinel.record)


async def test_project_returns_false_when_source_record_was_deleted() -> None:
    projector = MagicMock()
    projector.project_memory = AsyncMock()
    recovery = PostgresUserContextProjectionRecovery(
        config=PostgresUserContextStoreConfig(dsn="postgresql://example"),
        projector=projector,
    )
    recovery._one = AsyncMock(return_value=None)  # type: ignore[method-assign]

    projected = await recovery.project(ProjectionUpsertJob("memory", "principal-1", "memory-1", 2))

    assert projected is False
    projector.project_memory.assert_not_awaited()


async def test_project_rejects_unknown_projection_kind() -> None:
    recovery = PostgresUserContextProjectionRecovery(
        config=PostgresUserContextStoreConfig(dsn="postgresql://example"),
        projector=MagicMock(),
    )

    with pytest.raises(ValueError, match="unsupported projection kind 'unknown'"):
        await recovery.project(ProjectionUpsertJob("unknown", "principal-1", "record-1", 0))


def test_projection_job_key_preserves_queue_identity() -> None:
    job = ProjectionUpsertJob("memory", "principal-1", "memory-1", 3)

    assert job.key == ("memory", "principal-1", "memory-1")


async def test_queue_lifecycle_mutations_preserve_identity_and_bound_errors() -> None:
    recovery, connection = _recovery_with_connection()
    job = ProjectionUpsertJob("memory", "principal-1", "memory-1", 3)
    long_error = "x" * 600

    await recovery.complete(job)
    await recovery.retry(job, available_at=NOW, error=long_error)
    await recovery.dead_letter(job, error=long_error)

    assert connection.execute.await_args_list == [
        call(
            "DELETE FROM user_context_projection_upsert_queue "
            "WHERE projection_kind = %s AND principal_id = %s AND record_id = %s",
            job.key,
        ),
        call(
            "UPDATE user_context_projection_upsert_queue SET attempts = attempts + 1, "
            "available_at = %s, leased_until = NULL, last_error = %s "
            "WHERE projection_kind = %s AND principal_id = %s AND record_id = %s",
            (NOW, long_error[:500], *job.key),
        ),
        call(
            "UPDATE user_context_projection_upsert_queue SET attempts = attempts + 1, "
            "available_at = 'infinity', leased_until = NULL, last_error = %s "
            "WHERE projection_kind = %s AND principal_id = %s AND record_id = %s",
            (("dead-letter:" + long_error)[:500], *job.key),
        ),
    ]


@pytest.mark.parametrize(
    ("limit", "lease_seconds", "message"),
    [
        (0, 300, "limit MUST be in"),
        (5001, 300, "limit MUST be in"),
        (1, 0, "lease_seconds MUST be in"),
        (1, 3601, "lease_seconds MUST be in"),
    ],
)
async def test_claim_rejects_out_of_range_bounds(
    limit: int,
    lease_seconds: int,
    message: str,
) -> None:
    recovery = PostgresUserContextProjectionRecovery(
        config=PostgresUserContextStoreConfig(dsn="postgresql://example"),
        projector=MagicMock(),
    )

    with pytest.raises(ValueError, match=message):
        await recovery.claim(now=NOW, limit=limit, lease_seconds=lease_seconds)
