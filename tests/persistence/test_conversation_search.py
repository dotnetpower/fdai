from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.delivery.persistence import (
    PostgresConversationHistoryStore,
    PostgresConversationSearch,
    PostgresUserContextStoreConfig,
)
from fdai.shared.providers import (
    ConversationRecord,
    ConversationSearchMode,
    ConversationSearchQuery,
    ConversationSearchScope,
    ConversationTurnRecord,
    ConversationTurnRole,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 7, 20, 4, tzinfo=UTC)


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


@pytest.mark.integration
async def test_postgres_search_is_scoped_bilingual_and_cascade_deleted() -> None:
    dsn = _dsn()
    _upgrade()
    suffix = uuid.uuid4().hex
    config = PostgresUserContextStoreConfig(dsn=dsn)
    history = PostgresConversationHistoryStore(config=config)
    search = PostgresConversationSearch(config=config)
    principal_a = f"principal-a-{suffix}"
    principal_b = f"principal-b-{suffix}"
    conversation_a = f"conversation-a-{suffix}"
    conversation_b = f"conversation-b-{suffix}"
    for principal, conversation in (
        (principal_a, conversation_a),
        (principal_b, conversation_b),
    ):
        await history.create_conversation(
            ConversationRecord(
                conversation_id=conversation,
                principal_id=principal,
                channel_id="web",
                started_at=_NOW,
                last_active=_NOW + timedelta(minutes=2),
            )
        )
    for index, content in enumerate(
        (
            "Investigate the database latency regression.",
            "데이터베이스 지연 원인은 배포 변경입니다.",
            "Record the rollback decision.",
        )
    ):
        await history.append_turn(
            ConversationTurnRecord(
                turn_id=f"turn-a-{index}-{suffix}",
                conversation_id=conversation_a,
                principal_id=principal_a,
                turn_index=index,
                role=(
                    ConversationTurnRole.ASSISTANT if index == 1 else ConversationTurnRole.OPERATOR
                ),
                content=content,
                recorded_at=_NOW + timedelta(minutes=index),
                idempotency_key=f"a-{index}-{suffix}",
                metadata=(
                    {"incident_id": "incident-1", "correlation_id": "correlation-1"}
                    if index == 1
                    else {}
                ),
            )
        )
    await history.append_turn(
        ConversationTurnRecord(
            turn_id=f"turn-secret-{suffix}",
            conversation_id=conversation_b,
            principal_id=principal_b,
            turn_index=0,
            role=ConversationTurnRole.OPERATOR,
            content="Investigate the database latency regression.",
            recorded_at=_NOW,
            idempotency_key=f"secret-{suffix}",
        )
    )
    scope = ConversationSearchScope(principal_id=principal_a)

    english = await search.search(
        scope=scope,
        query=ConversationSearchQuery(text="database latency"),
    )
    korean = await search.search(
        scope=scope,
        query=ConversationSearchQuery(
            text="데이터베이스 지연 원인",
            mode=ConversationSearchMode.PHRASE,
            incident_id="incident-1",
        ),
    )
    prefix = await search.search(
        scope=scope,
        query=ConversationSearchQuery(
            text="invest regre",
            mode=ConversationSearchMode.PREFIX,
        ),
    )

    assert [hit.turn_id for hit in english.hits] == [f"turn-a-0-{suffix}"]
    assert [hit.turn_id for hit in korean.hits] == [f"turn-a-1-{suffix}"]
    assert [hit.turn_id for hit in prefix.hits] == [f"turn-a-0-{suffix}"]
    assert english.index_rows == 3

    context = await search.context(
        scope=scope,
        result_id=f"conversation-search:turn-a-1-{suffix}",
        before=1,
        after=1,
    )
    denied = await search.context(
        scope=scope,
        result_id=f"conversation-search:turn-secret-{suffix}",
    )
    lineage = await search.lineage(scope=scope, conversation_id=conversation_a)

    assert context is not None
    assert [hit.turn_id for hit in context.before] == [f"turn-a-0-{suffix}"]
    assert [hit.turn_id for hit in context.after] == [f"turn-a-2-{suffix}"]
    assert denied is None
    assert lineage is not None
    assert len(lineage.turn_ids) == 3

    assert await history.delete_conversation(
        principal_id=principal_a,
        conversation_id=conversation_a,
    )
    assert (
        await search.search(scope=scope, query=ConversationSearchQuery(text="database"))
    ).hits == ()
    assert await search.lineage(scope=scope, conversation_id=conversation_a) is None
    rebuild = await search.rebuild_projection()
    assert rebuild["index_rows"] >= 0
    assert rebuild["index_bytes"] >= 0
    assert rebuild["duration_ms"] >= 0


def test_query_rejects_wildcard_only_and_bad_windows() -> None:
    with pytest.raises(ValueError, match="letter or digit"):
        ConversationSearchQuery(text="%%%___")
    with pytest.raises(ValueError, match="earlier"):
        ConversationSearchQuery(
            text="valid",
            recorded_after=_NOW,
            recorded_before=_NOW,
        )


@pytest.mark.integration
async def test_retention_purge_removes_search_visibility_atomically() -> None:
    dsn = _dsn()
    _upgrade()
    suffix = uuid.uuid4().hex
    config = PostgresUserContextStoreConfig(dsn=dsn)
    history = PostgresConversationHistoryStore(config=config)
    search = PostgresConversationSearch(config=config)
    principal = f"principal-retention-{suffix}"
    conversation = f"conversation-retention-{suffix}"
    old = datetime(1999, 1, 1, tzinfo=UTC)
    await history.create_conversation(ConversationRecord(conversation, principal, "web", old, old))
    await history.append_turn(
        ConversationTurnRecord(
            turn_id=f"turn-retention-{suffix}",
            conversation_id=conversation,
            principal_id=principal,
            turn_index=0,
            role=ConversationTurnRole.OPERATOR,
            content="Retention searchable marker.",
            recorded_at=old,
            idempotency_key=f"retention-{suffix}",
        )
    )
    scope = ConversationSearchScope(principal_id=principal)
    assert (
        len((await search.search(scope=scope, query=ConversationSearchQuery(text="marker"))).hits)
        == 1
    )

    purged = await history.purge_inactive(
        before=datetime(2000, 1, 1, tzinfo=UTC),
        limit=100,
    )

    assert any(item.conversation_id == conversation for item in purged)
    assert (
        await search.search(scope=scope, query=ConversationSearchQuery(text="marker"))
    ).hits == ()
