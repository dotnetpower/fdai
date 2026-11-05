from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fdai.core.human_assignment import (
    GoalEvidence,
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


class Admission:
    def __init__(self, available=True):
        self.available = available

    async def verify(self, **kwargs):
        return self.available

    async def verify_subject(self, **kwargs):
        return self.available


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
        evidence=(GoalEvidence("source-1", _DIGEST_A, "document_span"),),
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
    retrieval = HandoverKnowledgeRetrieval(query=query, admission=Admission())
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
        await HandoverKnowledgeRetrieval(query=query, admission=Admission()).search(
            goal=_goal(),
            question="rollback",
            access=HandoverKnowledgeAccessContext(
                principal_ref="subject-1",
                collection_id="handover",
                allowed_access_refs=frozenset({"user:subject-1"}),
            ),
        )


@pytest.mark.parametrize("admitted", [None, False])
async def test_stale_chunk_acl_metadata_never_substitutes_for_current_source_admission(admitted):
    query = Query(
        (
            KnowledgeChunk(
                doc_id="doc-1",
                chunk_id="doc-1#1",
                text="Previously indexed text.",
                source_ref="source-1",
                metadata={"goal_ref": "goal-1", "access_descriptor_ref": "user:subject-1"},
            ),
        )
    )
    access = HandoverKnowledgeAccessContext("subject-1", "handover", frozenset({"user:subject-1"}))
    retrieval = HandoverKnowledgeRetrieval(
        query=query,
        admission=Admission(False) if admitted is False else None,
    )
    with pytest.raises(PermissionError, match="current source"):
        await retrieval.search(goal=_goal(), question="rollback", access=access)
    assert query.calls == []


async def test_canonical_document_citation_cannot_bypass_chunk_provenance():
    document, version = uuid4(), uuid4()
    reference = f"doc:{document}:{version}"
    goal = replace(_goal(), evidence=(GoalEvidence(reference, _DIGEST_A, "document_span"),))
    query = Query(
        (
            KnowledgeChunk(
                doc_id="different-document",
                chunk_id="different-chunk",
                text="Unbound source text.",
                source_ref=reference,
                metadata={"goal_ref": goal.goal_id, "access_descriptor_ref": "user:subject-1"},
            ),
        )
    )
    with pytest.raises(PermissionError, match="current source"):
        await HandoverKnowledgeRetrieval(query=query, admission=Admission()).search(
            goal=goal,
            question="rollback",
            access=HandoverKnowledgeAccessContext(
                "subject-1", "handover", frozenset({"user:subject-1"})
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


async def test_knowledge_handover_validation_and_governed_chunk_branches() -> None:
    with pytest.raises(ValueError, match="MUST be complete"):
        HandoverKnowledgeAccessContext("", "handover", frozenset({"user:subject-1"}))
    with pytest.raises(ValueError, match="MUST be in"):
        HandoverKnowledgeRetrieval(query=Query(()), limit=0)

    access = HandoverKnowledgeAccessContext("subject-1", "handover", frozenset({"user:subject-1"}))
    retrieval = HandoverKnowledgeRetrieval(query=Query(()), limit=1, admission=Admission())
    with pytest.raises(ValueError, match="question MUST be non-empty"):
        await retrieval.search(goal=_goal(), question="   ", access=access)

    # verify_subject passes but verify fails
    class SubjectOnlyAdmission:
        async def verify_subject(self, **kwargs):
            return True

        async def verify(self, **kwargs):
            return False

    with pytest.raises(PermissionError, match="current source admission"):
        await HandoverKnowledgeRetrieval(query=Query(()), admission=SubjectOnlyAdmission()).search(
            goal=_goal(), question="rollback", access=access
        )

    # len(chunks) > limit
    c1 = KnowledgeChunk(
        doc_id="doc-1",
        chunk_id="1",
        text="t1",
        source_ref="source-1",
        metadata={"goal_ref": "goal-1", "access_descriptor_ref": "user:subject-1"},
    )
    with pytest.raises(ValueError, match="exceeded its requested chunk bound"):
        await HandoverKnowledgeRetrieval(
            query=Query((c1, c1)), limit=1, admission=Admission()
        ).search(goal=_goal(), question="rollback", access=access)

    # _chunk_matches_evidence: non-uuid doc:a:b and valid governed doc:<uuid>:<uuid>
    doc_id, ver_id = uuid4(), uuid4()
    gov_ref = f"doc:{doc_id}:{ver_id}"
    goal_gov = replace(
        _goal(),
        evidence=(
            GoalEvidence("doc:not-uuid:v1", _DIGEST_A, "document_span"),
            GoalEvidence(gov_ref, _DIGEST_B, "document_span"),
        ),
    )
    gov_chunks = (
        KnowledgeChunk(
            doc_id="legacy-doc",
            chunk_id="legacy-1",
            text="Legacy non-UUID doc ref.",
            source_ref="doc:not-uuid:v1",
            metadata={"goal_ref": "goal-1", "access_descriptor_ref": "user:subject-1"},
        ),
        KnowledgeChunk(
            doc_id=f"governed:{doc_id}:{ver_id}",
            chunk_id="gov-1",
            text="Governed span text.",
            source_ref=f"document://{doc_id}/versions/{ver_id}#span-1",
            metadata={
                "goal_ref": "goal-1",
                "access_descriptor_ref": "user:subject-1",
                "document_id": str(doc_id),
                "version_id": str(ver_id),
                "source_sha256": _DIGEST_B,
            },
        ),
    )
    res_chunks = await HandoverKnowledgeRetrieval(
        query=Query(gov_chunks), admission=Admission()
    ).search(goal=goal_gov, question="rollback", access=access)
    assert len(res_chunks) == 2

    # HandoverKnowledgeClaim and publish_knowledge_conflict validation
    with pytest.raises(ValueError, match="MUST be non-empty"):
        HandoverKnowledgeClaim("", "goal-1", "k", "ref", _DIGEST_A)
    with pytest.raises(ValueError, match="MUST be SHA-256"):
        HandoverKnowledgeClaim("Mimir", "goal-1", "k", "ref", "not-sha")

    left = HandoverKnowledgeClaim("Mimir", "goal-1", "k1", "ref1", _DIGEST_A)
    right_diff_key = HandoverKnowledgeClaim("Norns", "goal-1", "k2", "ref2", _DIGEST_B)
    right_same_key = HandoverKnowledgeClaim("Norns", "goal-1", "k1", "ref2", _DIGEST_B)
    bus = InMemoryEventBus()
    with pytest.raises(ValueError, match="same goal and claim key"):
        await publish_knowledge_conflict(
            left=left, right=right_diff_key, bus=bus, topic="t", now=_NOW
        )
    with pytest.raises(ValueError, match="topic MUST be non-empty"):
        await publish_knowledge_conflict(
            left=left, right=right_same_key, bus=bus, topic="  ", now=_NOW
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        await publish_knowledge_conflict(
            left=left,
            right=right_same_key,
            bus=bus,
            topic="t",
            now=datetime(2026, 9, 5, 8, 0),
        )
