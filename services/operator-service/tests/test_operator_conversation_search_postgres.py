from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from fdai_operator_service.families.conversation import ConversationQuery, PrincipalScope
from fdai_operator_service.family_adapters import PostgresConversationAdapters
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)


def _dsn(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.mark.integration
async def test_operator_conversation_search_is_live_scoped_and_timing_free() -> None:
    admin_dsn = _dsn("FDAI_ADMIN_DATABASE_URL")
    operator_dsn = _dsn("FDAI_DATABASE_URL")
    suffix = uuid4().hex
    principal = f"operator-search-{suffix}"
    other_principal = f"operator-search-other-{suffix}"
    conversation = f"conversation-{suffix}"
    other_conversation = f"conversation-other-{suffix}"
    now = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
    async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
        for owner, conversation_id in (
            (principal, conversation),
            (other_principal, other_conversation),
        ):
            await connection.execute(
                "INSERT INTO conversation_record "
                "(conversation_id, principal_id, channel_id, started_at, last_active, status) "
                "VALUES (%s, %s, %s, %s, %s, 'active')",
                (conversation_id, owner, "web", now, now),
            )
            await connection.execute(
                "INSERT INTO conversation_turn "
                "(turn_id, conversation_id, principal_id, turn_index, role, content, "
                "recorded_at, idempotency_key, metadata) "
                "VALUES (%s, %s, %s, 0, 'operator', %s, %s, %s, %s::jsonb)",
                (
                    f"turn-{owner}",
                    conversation_id,
                    owner,
                    "Database latency marker.",
                    now,
                    f"key-{owner}",
                    '{"incident_id":"incident-one","evidence_refs":["audit:one"]}',
                ),
            )
        await connection.commit()
    try:
        store = PostgresFamilyStore(PostgresFamilyStoreConfig(dsn=operator_dsn))
        assert await store.probe_readiness() is True
        adapter = PostgresConversationAdapters(store)
        scope = PrincipalScope(subject_id=principal, roles=frozenset({"Reader"}))
        search = await adapter.read(
            ConversationQuery(
                operation="user.conversations.search",
                scope=scope,
                query={"q": "database latency", "mode": "terms", "limit": "20"},
            )
        )
        assert isinstance(search.body, dict)
        assert [item["conversation_id"] for item in search.body["hits"]] == [conversation]
        assert search.body["index_rows"] == 1
        assert "query_ms" not in search.body
        context = await adapter.read(
            ConversationQuery(
                operation="user.conversations.search_context",
                scope=scope,
                query={"before": "1", "after": "1"},
                path_params={"result_id": f"conversation-search:turn-{principal}"},
            )
        )
        lineage = await adapter.read(
            ConversationQuery(
                operation="user.conversations.lineage",
                scope=scope,
                path_params={"conversation_id": conversation},
            )
        )
        assert (
            isinstance(context.body, dict) and context.body["hit"]["turn_id"] == f"turn-{principal}"
        )
        assert isinstance(lineage.body, dict) and lineage.body["turn_ids"] == [f"turn-{principal}"]
        assert (
            await store.read_conversation_lineage(
                principal_id=principal,
                conversation_id=other_conversation,
            )
            is None
        )
    finally:
        async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
            await connection.execute(
                "DELETE FROM conversation_record WHERE principal_id = ANY(%s)",
                ([principal, other_principal],),
            )
            await connection.commit()
