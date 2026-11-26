from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing.ontology_instance import InMemoryOntologyInstanceStore
from fdai.shared.providers.user_context import (
    ConversationRecord,
    ConversationTurnRecord,
    ConversationTurnRole,
    UserMemoryCategory,
    UserMemoryFact,
    UserPreferenceRecord,
)

ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 7, 16, 7, 0, tzinfo=UTC)


def _projector() -> tuple[UserContextOntologyProjector, InMemoryOntologyInstanceStore]:
    registry = PackageResourceSchemaRegistry()
    objects = load_object_type_catalog(
        ROOT / "rule-catalog" / "vocabulary" / "object-types",
        schema_registry=registry,
    )
    links = load_link_type_catalog(
        ROOT / "rule-catalog" / "vocabulary" / "link-types",
        schema_registry=registry,
        object_types=objects,
    )
    store = InMemoryOntologyInstanceStore(object_types=objects, link_types=links)
    return UserContextOntologyProjector(store=store), store


async def test_projects_conversation_exchange_and_private_preference_metadata() -> None:
    projector, store = _projector()
    conversation = ConversationRecord("conversation-1", "principal-a", "web", NOW, NOW)
    operator = ConversationTurnRecord(
        "turn-1",
        conversation.conversation_id,
        conversation.principal_id,
        0,
        ConversationTurnRole.OPERATOR,
        "Show issues.",
        NOW,
        "request-1:operator",
    )
    assistant = ConversationTurnRecord(
        "turn-2",
        conversation.conversation_id,
        conversation.principal_id,
        1,
        ConversationTurnRole.ASSISTANT,
        "No high issues.",
        NOW,
        "request-1:assistant",
    )
    turn_id = await projector.project_turn_exchange(
        conversation=conversation, operator=operator, assistant=assistant
    )
    preference_id = await projector.project_preference(
        UserPreferenceRecord(
            principal_id="principal-a", locale="ko", timezone="Asia/Seoul", updated_at=NOW
        )
    )

    snapshot = await store.traverse(
        root_ids=("principal:principal-a",), direction="both", max_depth=2
    )
    assert {item.object_type for item in snapshot.objects} >= {
        "Principal",
        "Conversation",
        "Turn",
        "UserPreference",
    }
    stored_turn = await store.get_object(turn_id)
    assert stored_turn is not None
    assert stored_turn.properties["question_ref"] == "conversation-turn:conversation-1:turn-1"
    assert stored_turn.properties["answer_ref"] == "conversation-turn:conversation-1:turn-2"
    assert stored_turn.properties["question_sha256"] == hashlib.sha256(b"Show issues.").hexdigest()
    assert stored_turn.properties["answer_sha256"] == hashlib.sha256(b"No high issues.").hexdigest()
    assert "Show issues." not in str(stored_turn.properties)
    assert "No high issues." not in str(stored_turn.properties)
    assert await store.get_object(preference_id) is not None


async def test_memory_projection_excludes_private_body_and_delete_removes_links() -> None:
    projector, store = _projector()
    memory = UserMemoryFact(
        memory_id="memory-1",
        principal_id="principal-a",
        category=UserMemoryCategory.GOAL,
        body="Private body that must not enter ontology.",
        source_turn_id="turn-1",
        consented_at=NOW,
        created_at=NOW,
    )
    memory_id = await projector.project_memory(memory)
    stored = await store.get_object(memory_id)
    assert stored is not None
    assert "body" not in stored.properties
    assert "Private body" not in str(stored.properties)

    assert await projector.delete(memory_id) is True
    snapshot = await store.traverse(
        root_ids=("principal:principal-a",), direction="both", max_depth=2
    )
    assert all(link.from_id != memory_id and link.to_id != memory_id for link in snapshot.links)
