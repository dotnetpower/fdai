from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.shared.providers.testing.user_context import (
    InMemoryConversationHistoryStore,
    InMemoryUserMemoryStore,
    InMemoryUserPreferenceStore,
)
from fdai.shared.providers.user_context import (
    ConversationRecord,
    ConversationTurnRecord,
    ConversationTurnRole,
    UserContextConflictError,
    UserMemoryCategory,
    UserMemoryFact,
    UserPreferenceRecord,
)

NOW = datetime(2026, 7, 16, 7, 0, tzinfo=UTC)


async def test_conversation_history_is_principal_scoped_and_idempotent() -> None:
    store = InMemoryConversationHistoryStore()
    conversation = ConversationRecord(
        conversation_id="conversation-1",
        principal_id="principal-a",
        channel_id="web",
        started_at=NOW,
        last_active=NOW,
    )
    await store.create_conversation(conversation)
    turn = ConversationTurnRecord(
        turn_id="turn-1",
        conversation_id=conversation.conversation_id,
        principal_id=conversation.principal_id,
        turn_index=0,
        role=ConversationTurnRole.OPERATOR,
        content="Show recent incidents.",
        recorded_at=NOW,
        idempotency_key="request-1:operator",
    )

    assert await store.append_turn(turn) == turn
    assert await store.append_turn(replace(turn, recorded_at=NOW + timedelta(seconds=1))) == turn
    assert (
        await store.list_turns(
            principal_id="principal-b", conversation_id=conversation.conversation_id
        )
        == ()
    )
    assert (
        await store.get_conversation(
            principal_id="principal-b", conversation_id=conversation.conversation_id
        )
        is None
    )


async def test_conversation_rejects_conflicting_turn_index() -> None:
    store = InMemoryConversationHistoryStore()
    await store.create_conversation(
        ConversationRecord("conversation-1", "principal-a", "web", NOW, NOW)
    )
    first = ConversationTurnRecord(
        "turn-1",
        "conversation-1",
        "principal-a",
        0,
        ConversationTurnRole.OPERATOR,
        "First",
        NOW,
        "request-1",
    )
    second = ConversationTurnRecord(
        "turn-2",
        "conversation-1",
        "principal-a",
        0,
        ConversationTurnRole.OPERATOR,
        "Second",
        NOW,
        "request-2",
    )
    await store.append_turn(first)

    with pytest.raises(UserContextConflictError, match="turn index"):
        await store.append_turn(second)


async def test_conversation_atomic_allocation_exceeds_history_page_limit() -> None:
    store = InMemoryConversationHistoryStore()
    await store.create_conversation(
        ConversationRecord("conversation-1", "principal-a", "web", NOW, NOW)
    )

    last = None
    for index in range(1002):
        last = await store.append_turn(
            ConversationTurnRecord(
                f"turn-{index}",
                "conversation-1",
                "principal-a",
                0,
                ConversationTurnRole.OPERATOR,
                f"Turn {index}",
                NOW,
                f"request-{index}",
            ),
            allocate_index=True,
        )

    assert last is not None
    assert last.turn_index == 1001
    assert (
        len(
            await store.list_all_turns(
                principal_id="principal-a",
                conversation_id="conversation-1",
            )
        )
        == 1002
    )
    assert (
        await store.list_all_turns(
            principal_id="principal-b",
            conversation_id="conversation-1",
        )
        == ()
    )


async def test_preferences_use_optimistic_revision_and_principal_partition() -> None:
    store = InMemoryUserPreferenceStore()
    created = await store.put(UserPreferenceRecord(principal_id="principal-a"))
    assert created.revision == 1
    updated = await store.put(
        UserPreferenceRecord(
            principal_id="principal-a",
            locale="ko",
            verbosity="detailed",
            timezone="Asia/Seoul",
            updated_at=NOW,
        ),
        expected_revision=1,
    )
    assert updated.revision == 2
    assert await store.get(principal_id="principal-b") is None
    with pytest.raises(UserContextConflictError, match="revision mismatch"):
        await store.put(updated, expected_revision=1)


async def test_user_memory_requires_consent_source_and_filters_expired() -> None:
    store = InMemoryUserMemoryStore()
    active = UserMemoryFact(
        memory_id="memory-1",
        principal_id="principal-a",
        category=UserMemoryCategory.GOAL,
        body="Prefer a morning incident briefing.",
        source_turn_id="turn-1",
        consented_at=NOW,
        created_at=NOW,
    )
    expired = UserMemoryFact(
        memory_id="memory-2",
        principal_id="principal-a",
        category=UserMemoryCategory.CONTEXT,
        body="Temporary context.",
        source_turn_id="turn-2",
        consented_at=NOW,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )
    await store.create(active)
    await store.create(expired)

    assert await store.list_active(principal_id="principal-b", now=NOW) == ()
    result = await store.list_active(principal_id="principal-a", now=NOW + timedelta(minutes=2))
    assert result == (active,)

    purged = await store.purge_expired(now=NOW + timedelta(minutes=2))
    assert purged == (expired,)


async def test_conversation_retention_purges_inactive_history() -> None:
    store = InMemoryConversationHistoryStore()
    old = ConversationRecord(
        "old",
        "principal-a",
        "web",
        NOW - timedelta(days=100),
        NOW - timedelta(days=100),
    )
    current = ConversationRecord("current", "principal-a", "web", NOW, NOW)
    await store.create_conversation(old)
    await store.create_conversation(current)

    purged = await store.purge_inactive(before=NOW - timedelta(days=90))

    assert purged == (old,)
    assert await store.get_conversation(principal_id="principal-a", conversation_id="old") is None
    assert (
        await store.get_conversation(principal_id="principal-a", conversation_id="current")
        == current
    )


def test_user_context_rejects_unscoped_or_unconsented_shapes() -> None:
    with pytest.raises(ValueError, match="principal_id"):
        UserPreferenceRecord(principal_id="")
    with pytest.raises(ValueError, match="source_turn_id"):
        UserMemoryFact(
            memory_id="memory-1",
            principal_id="principal-a",
            category=UserMemoryCategory.PREFERENCE,
            body="Remember this.",
            source_turn_id="",
            consented_at=NOW,
            created_at=NOW,
        )
