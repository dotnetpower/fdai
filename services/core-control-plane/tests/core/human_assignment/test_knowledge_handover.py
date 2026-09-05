from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.human_assignment import (
    HandoverGoal,
    HandoverKnowledgeAccessContext,
    HandoverKnowledgeClaim,
    HandoverKnowledgeRetrieval,
    publish_knowledge_conflict,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai_service_contracts import KnowledgeChunk

_NOW = datetime(2026, 9, 5, 8, 0, tzinfo=UTC)
_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64


class Query:
    def __init__(self, chunks: tuple[KnowledgeChunk, ...]) -> None:
        self.chunks = chunks
        self.calls: list[tuple[str, str, frozenset[str], int]] = []

    async def search(
        self,
        query: str,
        *,
        collection_id: str,
        allowed_access_refs: frozenset[str],
        k: int = 5,
    ):
        self.calls.append((query, collection_id, allowed_access_refs, k))
        return self.chunks


def _goal() -> HandoverGoal:
    return HandoverGoal(
        goal_id="goal-1",
        assignment_case_id="case-1",
        subject_ref="subject-1",
        agent_name="Muninn",
        scope_ref="scope:platform",
        prompt_ref="prompt:runbook",
        priority=90,
        created_at=_NOW,
    )


async def test_retrieval_requires_goal_owner_and_exact_source_acl() -> None:
    query = Query(
        (
            KnowledgeChunk(
                doc_id="doc-1",
                chunk_id="doc-1#1",
                text="Authorized runbook text.",
                source_ref="source-1",
                metadata={
                    "goal_ref": "goal-1",
                    "access_descriptor_ref": "user:subject-1",
                },
            ),
            KnowledgeChunk(
                doc_id="doc-2",
                chunk_id="doc-2#1",
                text="Different goal.",
                source_ref="source-2",
                metadata={
                    "goal_ref": "goal-2",
                    "access_descriptor_ref": "user:subject-1",
                },
            ),
        )
    )
    retrieval = HandoverKnowledgeRetrieval(query=query)
    access = HandoverKnowledgeAccessContext(
        principal_ref="subject-1",
        collection_id="handover",
        allowed_access_refs=frozenset({"user:subject-1"}),
    )

    chunks = await retrieval.search(goal=_goal(), question="rollback", access=access)

    assert tuple(item.chunk_id for item in chunks) == ("doc-1#1",)
    assert query.calls == [("rollback", "handover", frozenset({"user:subject-1"}), 10)]

    with pytest.raises(PermissionError, match="does not own"):
        await retrieval.search(
            goal=_goal(),
            question="rollback",
            access=HandoverKnowledgeAccessContext(
                principal_ref="different-subject",
                collection_id="handover",
                allowed_access_refs=frozenset({"user:different-subject"}),
            ),
        )


async def test_retrieval_surfaces_provider_acl_leak() -> None:
    query = Query(
        (
            KnowledgeChunk(
                doc_id="doc-1",
                chunk_id="doc-1#1",
                text="Leaked text.",
                source_ref="source-1",
                metadata={
                    "goal_ref": "goal-1",
                    "access_descriptor_ref": "group:other",
                },
            ),
        )
    )

    with pytest.raises(PermissionError, match="outside the source ACL"):
        await HandoverKnowledgeRetrieval(query=query).search(
            goal=_goal(),
            question="rollback",
            access=HandoverKnowledgeAccessContext(
                principal_ref="subject-1",
                collection_id="handover",
                allowed_access_refs=frozenset({"user:subject-1"}),
            ),
        )


async def test_conflict_event_is_content_free_and_never_promotable() -> None:
    bus = InMemoryEventBus()
    left = HandoverKnowledgeClaim(
        agent_name="Mimir",
        goal_ref="goal-1",
        claim_key="rollback-threshold",
        evidence_ref="document:one",
        evidence_digest=_DIGEST_A,
    )
    right = HandoverKnowledgeClaim(
        agent_name="Norns",
        goal_ref="goal-1",
        claim_key="rollback-threshold",
        evidence_ref="document:two",
        evidence_digest=_DIGEST_B,
    )

    event = await publish_knowledge_conflict(
        left=left,
        right=right,
        bus=bus,
        topic="fdai.events",
        now=_NOW,
    )
    published = await anext(bus.subscribe("fdai.events", "test"))

    assert event is not None
    assert published.payload["source"] == "Forseti"
    assert published.payload["event_type"] == "knowledge.conflict.detected"
    assert published.payload["payload"]["arbiter"] == "Odin"
    assert published.payload["payload"]["review_required"] is True
    assert published.payload["payload"]["may_promote"] is False
    assert "text" not in str(published.payload).lower()

    assert (
        await publish_knowledge_conflict(
            left=left,
            right=left,
            bus=bus,
            topic="fdai.events",
            now=_NOW,
        )
        is None
    )
