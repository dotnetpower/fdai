from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from fdai.delivery.persistence.postgres_user_context import (
    PostgresConversationHistoryStore,
    PostgresUserContextStoreConfig,
)


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
