from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fdai.delivery.persistence.postgres_user_context import (
    PostgresConversationHistoryStore,
    PostgresUserContextStoreConfig,
)
from fdai.shared.providers.user_context import (
    ConversationRecord,
    ConversationTurnRecord,
    ConversationTurnRole,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_NOW = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)


def _dsn() -> str:
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade() -> None:
    result = subprocess.run(  # noqa: S603 - controlled module invocation
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _connection(rows: list[dict[str, str]]) -> MagicMock:
    cursor = MagicMock()
    cursor.fetchall = AsyncMock(return_value=rows)
    connection = MagicMock()
    connection.__aenter__ = AsyncMock(return_value=connection)
    connection.__aexit__ = AsyncMock(return_value=None)
    connection.execute = AsyncMock(side_effect=(None, cursor))
    return connection


async def test_latest_operator_turn_ids_returns_principal_scoped_latest_rows() -> None:
    connection = _connection(
        [
            {"conversation_id": "conversation-1", "turn_id": "turn-3"},
            {"conversation_id": "conversation-2", "turn_id": "turn-8"},
        ]
    )
    store = PostgresConversationHistoryStore(
        config=PostgresUserContextStoreConfig(dsn="postgresql://example")
    )
    store._connect = AsyncMock(return_value=connection)  # type: ignore[method-assign]

    result = await store.latest_operator_turn_ids(
        principal_id="principal-1",
        conversation_ids=("conversation-1", "conversation-2"),
    )

    assert result == {"conversation-1": "turn-3", "conversation-2": "turn-8"}
    query, parameters = connection.execute.await_args_list[1].args
    assert "DISTINCT ON (conversation_id)" in query
    assert "role = 'operator'" in query
    assert parameters == (
        "principal-1",
        ["conversation-1", "conversation-2"],
    )


async def test_latest_operator_turn_ids_skips_database_for_empty_input() -> None:
    store = PostgresConversationHistoryStore(
        config=PostgresUserContextStoreConfig(dsn="postgresql://example")
    )
    connect = AsyncMock()
    store._connect = connect  # type: ignore[method-assign]

    assert (
        await store.latest_operator_turn_ids(
            principal_id="principal-1",
            conversation_ids=(),
        )
        == {}
    )
    connect.assert_not_awaited()


async def test_first_operator_questions_returns_bounded_principal_scoped_rows() -> None:
    connection = _connection(
        [{"conversation_id": "conversation-1", "content": "First question..."}]
    )
    store = PostgresConversationHistoryStore(
        config=PostgresUserContextStoreConfig(dsn="postgresql://example")
    )
    store._connect = AsyncMock(return_value=connection)  # type: ignore[method-assign]

    result = await store.first_operator_questions(
        principal_id="principal-1",
        conversation_ids=("conversation-1",),
        max_chars=16,
    )

    assert result == {"conversation-1": "First question..."}
    query, parameters = connection.execute.await_args_list[1].args
    assert "DISTINCT ON (conversation_id)" in query
    assert "ORDER BY conversation_id, turn_index" in query
    assert parameters == (16, 13, "principal-1", ["conversation-1"])


async def test_list_conversations_uses_stable_cursor_order() -> None:
    connection = _connection([])
    store = PostgresConversationHistoryStore(
        config=PostgresUserContextStoreConfig(dsn="postgresql://example")
    )
    store._connect = AsyncMock(return_value=connection)  # type: ignore[method-assign]
    before = datetime.fromisoformat("2026-08-03T10:00:00+00:00")

    await store.list_conversations(
        principal_id="principal-1",
        limit=101,
        before_last_active=before,
        before_conversation_id="conversation-100",
    )

    query, parameters = connection.execute.await_args_list[1].args
    assert "(last_active, conversation_id) < (%s, %s)" in query
    assert "ORDER BY last_active DESC, conversation_id DESC" in query
    assert parameters == ("principal-1", before, "conversation-100", 101)


@pytest.mark.integration
async def test_postgres_history_and_latest_context_survive_restart_with_scope() -> None:
    _upgrade()
    suffix = uuid4().hex
    principal_id = f"history-principal-{suffix}"
    other_principal_id = f"history-other-{suffix}"
    conversation_id = f"history-conversation-{suffix}"
    config = PostgresUserContextStoreConfig(dsn=_dsn())
    store = PostgresConversationHistoryStore(config=config)
    conversation = ConversationRecord(
        conversation_id=conversation_id,
        principal_id=principal_id,
        channel_id="web",
        started_at=_NOW,
        last_active=_NOW,
    )
    turns = (
        ConversationTurnRecord(
            turn_id=f"operator-first-{suffix}",
            conversation_id=conversation_id,
            principal_id=principal_id,
            turn_index=0,
            role=ConversationTurnRole.OPERATOR,
            content="  First   operator question  ",
            recorded_at=_NOW,
            idempotency_key=f"operator-first-{suffix}",
        ),
        ConversationTurnRecord(
            turn_id=f"assistant-{suffix}",
            conversation_id=conversation_id,
            principal_id=principal_id,
            turn_index=1,
            role=ConversationTurnRole.ASSISTANT,
            content="Bounded answer",
            recorded_at=_NOW + timedelta(seconds=1),
            idempotency_key=f"assistant-{suffix}",
        ),
        ConversationTurnRecord(
            turn_id=f"operator-latest-{suffix}",
            conversation_id=conversation_id,
            principal_id=principal_id,
            turn_index=2,
            role=ConversationTurnRole.OPERATOR,
            content="Follow-up question",
            recorded_at=_NOW + timedelta(seconds=2),
            idempotency_key=f"operator-latest-{suffix}",
        ),
    )

    await store.create_conversation(conversation)
    for turn in turns:
        await store.append_turn(turn)

    restarted = PostgresConversationHistoryStore(config=config)
    assert await restarted.get_conversation(
        principal_id=principal_id,
        conversation_id=conversation_id,
    ) == replace_last_active(conversation, turns[-1].recorded_at)
    assert (
        await restarted.get_conversation(
            principal_id=other_principal_id,
            conversation_id=conversation_id,
        )
        is None
    )
    assert (
        await restarted.list_all_turns(
            principal_id=principal_id,
            conversation_id=conversation_id,
        )
        == turns
    )
    assert (
        await restarted.list_all_turns(
            principal_id=other_principal_id,
            conversation_id=conversation_id,
        )
        == ()
    )
    assert await restarted.latest_operator_turn_ids(
        principal_id=principal_id,
        conversation_ids=(conversation_id,),
    ) == {conversation_id: turns[-1].turn_id}
    assert (
        await restarted.latest_operator_turn_ids(
            principal_id=other_principal_id,
            conversation_ids=(conversation_id,),
        )
        == {}
    )
    assert await restarted.first_operator_questions(
        principal_id=principal_id,
        conversation_ids=(conversation_id,),
        max_chars=100,
    ) == {conversation_id: "First operator question"}


def replace_last_active(record: ConversationRecord, last_active: datetime) -> ConversationRecord:
    return ConversationRecord(
        conversation_id=record.conversation_id,
        principal_id=record.principal_id,
        channel_id=record.channel_id,
        started_at=record.started_at,
        last_active=last_active,
        status=record.status,
    )
