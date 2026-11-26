"""The conversation history list includes semantic-turn sessions, not only legacy rows."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fdai_operator_service.families.conversation import ConversationQuery, PrincipalScope
from fdai_operator_service.family_adapters import PostgresConversationAdapters
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)

NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)


def _dsn(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _request(principal: str, session: str, utterance: str, at: datetime) -> tuple[str, str]:
    request_id = str(uuid4())
    value = {
        "kind": "operator.semantic_turn",
        "state": "completed",
        "request_id": request_id,
        "principal_id": principal,
        "accepted_at": at.isoformat(),
        "envelope": {
            "request_id": request_id,
            "semantic_turn": {
                "session_id": session,
                "utterance": utterance,
                "turn_id": f"turn-{request_id}",
            },
        },
    }
    return f"semantic-turn:{request_id}", json.dumps(value)


@pytest.mark.integration
async def test_semantic_sessions_are_listed_newest_first_inside_the_principal_scope() -> None:
    admin_dsn = _dsn("FDAI_ADMIN_DATABASE_URL")
    operator_dsn = _dsn("FDAI_DATABASE_URL")
    suffix = uuid4().hex
    principal = f"history-{suffix}"
    other = f"history-other-{suffix}"
    older, newer, legacy, foreign = (
        f"{name}-{suffix}" for name in ("older", "newer", "legacy", "x")
    )
    rows = [
        _request(principal, older, "first question of the older session", NOW),
        _request(
            principal, older, "second question of the older session", NOW + timedelta(minutes=1)
        ),
        _request(principal, newer, "only question of the newer session", NOW + timedelta(hours=1)),
        _request(other, foreign, "another principal's question", NOW + timedelta(hours=2)),
    ]
    async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
        for key, value in rows:
            await connection.execute(
                "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb)", (key, value)
            )
        await connection.execute(
            "INSERT INTO conversation_record "
            "(conversation_id, principal_id, channel_id, started_at, last_active, status) "
            "VALUES (%s, %s, %s, %s, %s, 'active')",
            (legacy, principal, "web", NOW - timedelta(days=1), NOW - timedelta(days=1)),
        )
        await connection.commit()
    try:
        adapter = PostgresConversationAdapters(
            PostgresFamilyStore(PostgresFamilyStoreConfig(dsn=operator_dsn))
        )
        page = await adapter.read(
            ConversationQuery(
                operation="user.conversations",
                scope=PrincipalScope(subject_id=principal, roles=frozenset({"Reader"})),
            )
        )

        assert isinstance(page.body, dict)
        listed = page.body["conversations"]
        assert isinstance(listed, list)
        assert [item["conversation_id"] for item in listed] == [newer, older, legacy]
        by_id = {item["conversation_id"]: item for item in listed}
        assert by_id[older]["first_operator_question"] == "first question of the older session"
        assert by_id[older]["started_at"] == NOW.isoformat().replace("+00:00", "Z") or (
            by_id[older]["started_at"].startswith("2026-08-14T08:00:00")
        )
        assert by_id[older]["last_active"].startswith("2026-08-14T08:01:00")
        assert by_id[older]["channel_id"]
        assert foreign not in by_id

        later = await adapter.read(
            ConversationQuery(
                operation="user.conversations",
                scope=PrincipalScope(subject_id=principal, roles=frozenset({"Reader"})),
                query={
                    "before_last_active": by_id[newer]["last_active"],
                    "before_conversation_id": newer,
                },
            )
        )
        assert isinstance(later.body, dict)
        assert [item["conversation_id"] for item in later.body["conversations"]] == [
            older,
            legacy,
        ]
    finally:
        async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
            await connection.execute(
                "DELETE FROM state_kv WHERE value ->> 'principal_id' = ANY(%s)",
                ([principal, other],),
            )
            await connection.execute(
                "DELETE FROM conversation_record WHERE principal_id = %s", (principal,)
            )
            await connection.commit()
