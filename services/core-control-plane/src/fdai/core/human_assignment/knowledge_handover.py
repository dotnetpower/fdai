"""ACL-bound retrieval and typed events for handover knowledge."""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai_service_contracts import DocumentSearch, KnowledgeChunk

from fdai.core.human_assignment.goal_admission import GoalEvidenceAdmission
from fdai.core.human_assignment.goals import HandoverGoal
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.event_bus import EventBus

_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_NAMESPACE = uuid.NAMESPACE_URL


@dataclass(frozen=True, slots=True)
class HandoverKnowledgeAccessContext:
    """Server-resolved access grants used for one principal's retrieval."""

    principal_ref: str
    collection_id: str
    allowed_access_refs: frozenset[str]

    def __post_init__(self) -> None:
        if (
            not self.principal_ref.strip()
            or not self.collection_id.strip()
            or not self.allowed_access_refs
            or any(not item.strip() for item in self.allowed_access_refs)
        ):
            raise ValueError("handover knowledge access context MUST be complete")


@dataclass(frozen=True, slots=True)
class HandoverKnowledgeRetrieval:
    """Read goal-bound chunks without crossing the source ACL."""

    query: DocumentSearch
    limit: int = 10
    admission: GoalEvidenceAdmission | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 20:
            raise ValueError("handover knowledge retrieval limit MUST be in [1, 20]")

    async def search(
        self,
        *,
        goal: HandoverGoal,
        question: str,
        access: HandoverKnowledgeAccessContext,
    ) -> tuple[KnowledgeChunk, ...]:
        """Admit the current subject and sources before reading content, then verify
        returned spans.
        """
        async with asyncio.timeout(30):
            return await self._search(goal=goal, question=question, access=access)

    async def _search(
        self,
        *,
        goal: HandoverGoal,
        question: str,
        access: HandoverKnowledgeAccessContext,
    ) -> tuple[KnowledgeChunk, ...]:
        if access.principal_ref != goal.subject_ref:
            raise PermissionError("handover knowledge principal does not own the goal")
        if self.admission is None or not await self.admission.verify_subject(
            subject_ref=goal.subject_ref, assignment_case_id=goal.assignment_case_id
        ):
            raise PermissionError("handover retrieval requires current source admission and ACL")
        for reference, digest in sorted(
            {(item.evidence_ref, item.digest) for item in goal.evidence}
        ):
            if not await self.admission.verify(
                subject_ref=goal.subject_ref,
                evidence_ref=reference,
                digest=digest,
                reviewer_ref=access.principal_ref,
            ):
                raise PermissionError(
                    "handover retrieval requires current source admission and ACL"
                )
        chunks = await self.query.search(
            question,
            collection_id=access.collection_id,
            allowed_access_refs=access.allowed_access_refs,
            k=self.limit,
        )
        if len(chunks) > self.limit:
            raise ValueError("handover query exceeded its requested chunk bound")
        verified: list[KnowledgeChunk] = []
        for chunk in chunks:
            metadata = chunk.metadata
            if metadata.get("goal_ref") != goal.goal_id:
                continue
            access_ref = metadata.get("access_descriptor_ref")
            if not isinstance(access_ref, str) or access_ref not in access.allowed_access_refs:
                raise PermissionError("document query returned a chunk outside the source ACL")
            evidence = next(
                (
                    item
                    for item in goal.evidence
                    if _chunk_matches_evidence(chunk, item.evidence_ref, item.digest)
                ),
                None,
            )
            if (
                evidence is None
                or self.admission is None
                or not await self.admission.verify(
                    subject_ref=goal.subject_ref,
                    reviewer_ref=access.principal_ref,
                    evidence_ref=evidence.evidence_ref,
                    digest=evidence.digest,
                )
            ):
                raise PermissionError(
                    "handover retrieval requires current source admission and ACL"
                )
            verified.append(chunk)
        return tuple(verified)


def _chunk_matches_evidence(chunk: KnowledgeChunk, reference: str, digest: str) -> bool:
    """Keep document identity separate from its original source-span citation.

    Legacy exact doc: chunks retain compatibility. Governed worker chunks keep their
    document:// locator and must additionally bind exact immutable ids and source hash.
    """
    parts = reference.split(":")
    if len(parts) != 3 or parts[0] != "doc":
        return chunk.source_ref == reference
    try:
        document, version = uuid.UUID(parts[1]), uuid.UUID(parts[2])
    except ValueError:
        return chunk.source_ref == reference
    prefix = f"document://{document}/versions/{version}#"
    metadata = chunk.metadata
    return (
        reference == f"doc:{document}:{version}"
        and (
            chunk.source_ref == reference
            or (chunk.source_ref.startswith(prefix) and len(chunk.source_ref) > len(prefix))
        )
        and metadata.get("document_id") == str(document)
        and metadata.get("version_id") == str(version)
        and metadata.get("source_sha256") == digest
        and chunk.doc_id == f"governed:{document}:{version}"
    )


@dataclass(frozen=True, slots=True)
class HandoverKnowledgeClaim:
    """Content-free reference to one agent-authored claim."""

    agent_name: str
    goal_ref: str
    claim_key: str
    evidence_ref: str
    evidence_digest: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.agent_name,
                self.goal_ref,
                self.claim_key,
                self.evidence_ref,
            )
        ):
            raise ValueError("handover knowledge claim references MUST be non-empty")
        if _DIGEST.fullmatch(self.evidence_digest) is None:
            raise ValueError("handover knowledge evidence_digest MUST be SHA-256")


async def publish_knowledge_conflict(
    *,
    left: HandoverKnowledgeClaim,
    right: HandoverKnowledgeClaim,
    bus: EventBus,
    topic: str,
    now: datetime | None = None,
) -> Event | None:
    """Publish a review-only conflict event for two incompatible claim digests."""

    if left.goal_ref != right.goal_ref or left.claim_key != right.claim_key:
        raise ValueError("knowledge conflict claims MUST address the same goal and claim key")
    if left.evidence_digest == right.evidence_digest:
        return None
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    material = (
        f"{left.goal_ref}\0{left.claim_key}\0"
        f"{min(left.evidence_digest, right.evidence_digest)}\0"
        f"{max(left.evidence_digest, right.evidence_digest)}"
    )
    event = Event(
        schema_version="1.0.0",
        event_id=uuid.uuid5(_NAMESPACE, f"handover-conflict:{material}"),
        idempotency_key=f"handover-conflict-{uuid.uuid5(_NAMESPACE, material)}",
        correlation_id=left.goal_ref,
        source="Forseti",
        event_type="knowledge.conflict.detected",
        resource_ref=f"handover-goal:{left.goal_ref}",
        payload={
            "goal_ref": left.goal_ref,
            "claim_key": left.claim_key,
            "evidence_refs": sorted({left.evidence_ref, right.evidence_ref}),
            "evidence_digests": sorted({left.evidence_digest, right.evidence_digest}),
            "claiming_agents": sorted({left.agent_name, right.agent_name}),
            "arbiter": "Odin",
            "review_required": True,
            "may_promote": False,
        },
        detected_at=timestamp,
        ingested_at=timestamp,
        mode=Mode.SHADOW,
    )
    await bus.publish(topic, key=left.goal_ref, payload=event.model_dump(mode="json"))
    return event


__all__ = [
    "HandoverKnowledgeAccessContext",
    "HandoverKnowledgeClaim",
    "HandoverKnowledgeRetrieval",
    "publish_knowledge_conflict",
]
