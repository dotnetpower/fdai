from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fdai.shared.providers import (
    ConversationRecord,
    ConversationSearchMode,
    ConversationSearchQuery,
    ConversationSearchScope,
    ConversationTurnRecord,
    ConversationTurnRole,
)
from fdai.shared.providers.testing import (
    InMemoryConversationHistoryStore,
    InMemoryConversationSearch,
)

_NOW = datetime(2026, 7, 20, 3, tzinfo=UTC)


async def _seed() -> tuple[InMemoryConversationHistoryStore, InMemoryConversationSearch]:
    history = InMemoryConversationHistoryStore()
    for principal, conversation, channel in (
        ("principal-a", "conversation-a", "web"),
        ("principal-a", "conversation-b", "teams"),
        ("principal-b", "conversation-secret", "web"),
    ):
        await history.create_conversation(
            ConversationRecord(
                conversation_id=conversation,
                principal_id=principal,
                channel_id=channel,
                started_at=_NOW,
                last_active=_NOW + timedelta(minutes=3),
            )
        )
    turns = (
        ConversationTurnRecord(
            turn_id="turn-a-1",
            conversation_id="conversation-a",
            principal_id="principal-a",
            turn_index=0,
            role=ConversationTurnRole.OPERATOR,
            content="Investigate the database latency regression.",
            recorded_at=_NOW,
            idempotency_key="a-1",
        ),
        ConversationTurnRecord(
            turn_id="turn-a-2",
            conversation_id="conversation-a",
            principal_id="principal-a",
            turn_index=1,
            role=ConversationTurnRole.ASSISTANT,
            content="데이터베이스 지연 원인은 배포 변경입니다.",
            recorded_at=_NOW + timedelta(minutes=1),
            idempotency_key="a-2",
            metadata={
                "incident_id": "incident-1",
                "correlation_id": "correlation-1",
                "evidence_refs": json.dumps(["audit:1", "trace:1"]),
            },
        ),
        ConversationTurnRecord(
            turn_id="turn-a-3",
            conversation_id="conversation-a",
            principal_id="principal-a",
            turn_index=2,
            role=ConversationTurnRole.OPERATOR,
            content="Record the rollback decision.",
            recorded_at=_NOW + timedelta(minutes=2),
            idempotency_key="a-3",
        ),
        ConversationTurnRecord(
            turn_id="turn-b-1",
            conversation_id="conversation-b",
            principal_id="principal-a",
            turn_index=0,
            role=ConversationTurnRole.OPERATOR,
            content="Investigate the network route.",
            recorded_at=_NOW + timedelta(minutes=3),
            idempotency_key="b-1",
        ),
        ConversationTurnRecord(
            turn_id="turn-secret-1",
            conversation_id="conversation-secret",
            principal_id="principal-b",
            turn_index=0,
            role=ConversationTurnRole.OPERATOR,
            content="Investigate the database latency regression.",
            recorded_at=_NOW,
            idempotency_key="secret-1",
        ),
    )
    for turn in turns:
        await history.append_turn(turn)
    return history, InMemoryConversationSearch(history=history)


async def test_search_is_principal_and_scope_bound_before_metrics() -> None:
    _, search = await _seed()

    page = await search.search(
        scope=ConversationSearchScope(
            principal_id="principal-a",
            allowed_channels=frozenset({"web"}),
        ),
        query=ConversationSearchQuery(text="database latency"),
    )

    assert [hit.turn_id for hit in page.hits] == ["turn-a-1"]
    assert page.index_rows == 3
    assert all("secret" not in hit.conversation_id for hit in page.hits)


async def test_bilingual_phrase_prefix_and_metadata_filters() -> None:
    _, search = await _seed()
    scope = ConversationSearchScope(principal_id="principal-a")

    phrase = await search.search(
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
            channels=("web",),
            roles=(ConversationTurnRole.OPERATOR,),
        ),
    )

    assert [hit.turn_id for hit in phrase.hits] == ["turn-a-2"]
    assert phrase.hits[0].evidence_refs == ("audit:1", "trace:1")
    assert [hit.turn_id for hit in prefix.hits] == ["turn-a-1"]


async def test_context_lineage_and_deletion_remain_authorized() -> None:
    history, search = await _seed()
    scope = ConversationSearchScope(
        principal_id="principal-a",
        allowed_conversation_ids=frozenset({"conversation-a"}),
    )

    context = await search.context(
        scope=scope,
        result_id="conversation-search:turn-a-2",
        before=1,
        after=1,
    )
    denied = await search.context(
        scope=scope,
        result_id="conversation-search:turn-secret-1",
    )
    lineage = await search.lineage(scope=scope, conversation_id="conversation-a")

    assert context is not None
    assert [hit.turn_id for hit in context.before] == ["turn-a-1"]
    assert [hit.turn_id for hit in context.after] == ["turn-a-3"]
    assert denied is None
    assert lineage is not None
    assert lineage.turn_ids == ("turn-a-1", "turn-a-2", "turn-a-3")

    await history.delete_conversation(
        principal_id="principal-a",
        conversation_id="conversation-a",
    )

    assert await search.lineage(scope=scope, conversation_id="conversation-a") is None
    assert (
        await search.search(scope=scope, query=ConversationSearchQuery(text="database"))
    ).hits == ()


async def test_representative_corpus_reports_cap_latency_and_index_growth() -> None:
    history = InMemoryConversationHistoryStore()
    await history.create_conversation(
        ConversationRecord(
            conversation_id="conversation-corpus",
            principal_id="principal-corpus",
            channel_id="web",
            started_at=_NOW,
            last_active=_NOW + timedelta(minutes=250),
        )
    )
    for index in range(250):
        await history.append_turn(
            ConversationTurnRecord(
                turn_id=f"turn-corpus-{index}",
                conversation_id="conversation-corpus",
                principal_id="principal-corpus",
                turn_index=index,
                role=ConversationTurnRole.OPERATOR,
                content=f"Investigate latency sample {index} with bounded evidence.",
                recorded_at=_NOW + timedelta(minutes=index),
                idempotency_key=f"corpus-{index}",
            )
        )
    search = InMemoryConversationSearch(history=history)

    page = await search.search(
        scope=ConversationSearchScope(principal_id="principal-corpus"),
        query=ConversationSearchQuery(text="latency", limit=25),
    )

    assert len(page.hits) == 25
    assert page.result_cap == 25
    assert page.index_rows == 250
    assert page.index_bytes > 10_000
    assert page.query_ms >= 0
