"""Principal-scoped Core handover evidence on the existing governed-document query surface.

Responsibility: Retrieve currently admitted Core-goal chunks for an authenticated reader.
Boundary: Use restricted Core SQL functions and immutable citations, never raw document grants.
Authority and state: Read-only; neither a goal nor an excerpt grants instructions or execution.
Dependencies: Current Core goal admission and the existing optional governed-document reader.
Deployment: The same bounded reader is composed locally and deployed; no fixture fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai_service_contracts.cloud_knowledge import Applicability
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.human_assignment.knowledge_handover import HandoverKnowledgeAccessContext
from fdai.core.ontology_platform.governed_document_queries import (
    GovernedDocumentCollection,
    GovernedDocumentExcerpt,
    GovernedDocumentReader,
)
from fdai.runtime.core_handover import CoreHandoverServices
from fdai.shared.contracts.models import CeilingRole


@dataclass(frozen=True, slots=True)
class CoreHandoverDocumentReader:
    """Read only the current human's own Core goals; never infer scope from the query prose."""

    core: CoreHandoverServices
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def search(
        self,
        *,
        query: str,
        principal_ref: str,
        principal_role: CeilingRole,
        principal_groups: frozenset[str],
        purpose: str,
        limit: int,
        target: Applicability | None = None,
        exact_refs: tuple[str, ...] = (),
        context_source: str | None = None,
        conversation_ref: str | None = None,
        document_context_digest: str | None = None,
    ) -> GovernedDocumentCollection:
        """Serve real citations via query.governed_documents, always disclosing incomplete
        coverage.

        Authentication and purpose checks precede every SQL or identity read. Server-derived
        collection and ACL references only narrow exact subject-owned documents. Current
        goal, source, reviewer, or role failures abort the read without substituting content.
        """
        if (
            target is not None
            or exact_refs
            or context_source is not None
            or conversation_ref is not None
            or document_context_digest is not None
        ):
            raise PermissionError("scoped document context requires its governed source reader")
        if (
            purpose != "operations-review"
            or principal_role
            not in {
                CeilingRole.READER,
                CeilingRole.CONTRIBUTOR,
                CeilingRole.APPROVER,
                CeilingRole.OWNER,
            }
            or not isinstance(principal_ref, str)
            or not 1 <= len(principal_ref) <= 256
            or not isinstance(query, str)
            or not query.strip()
            or len(query) > 20_000
            or type(limit) is not int
            or not 1 <= limit <= 8
        ):
            raise PermissionError(
                "Core handover retrieval requires bounded authenticated read context"
            )
        async with asyncio.timeout(10):
            async with await self.core.source._connect() as connection:
                rows = await (
                    await connection.execute(
                        "SELECT value->>'goal_id' AS goal_id FROM state_kv "
                        "WHERE starts_with(key, 'handover_goal:goal:') "
                        "AND value->>'subject_ref'=%s "
                        "AND value->>'state' IN ('ready_for_review','accepted') "
                        "ORDER BY key LIMIT 5",
                        (principal_ref,),
                    )
                ).fetchall()
            excerpts: dict[tuple[str, str], GovernedDocumentExcerpt] = {}
            sources: list[dict[str, object]] = []
            for row in rows[:4]:
                goal = await self.core.goals.get_goal(row["goal_id"])
                if goal.subject_ref != principal_ref:
                    raise PermissionError("Core handover retrieval goal changed its subject")
                await self.core.goals.require_current_evidence(goal)
                async with await self.core.source._connect() as connection:
                    accesses = await (
                        await connection.execute(
                            "SELECT * FROM fdai_core_handover_goal_access(%s,%s,%s)",
                            (goal.goal_id, goal.revision, principal_ref),
                        )
                    ).fetchall()
                if len(accesses) > 4:
                    raise ValueError("Core handover retrieval exceeds its collection read bound")
                sources.append({"goal_id": goal.goal_id, "revision": goal.revision})
                for access in accesses:
                    chunks = await self.core.search(
                        goal_id=goal.goal_id,
                        question=query,
                        access=HandoverKnowledgeAccessContext(
                            principal_ref,
                            access["collection_id"],
                            frozenset({access["access_ref"]}),
                        ),
                    )
                    for chunk in chunks:
                        document = str(chunk.metadata["document_id"])
                        version = str(chunk.metadata["version_id"])
                        digest = str(chunk.metadata["source_sha256"])
                        excerpt = GovernedDocumentExcerpt(
                            evidence_ref="document:"
                            + content_digest(
                                {
                                    "document_id": document,
                                    "version_id": version,
                                    "source_sha256": digest,
                                    "chunk_id": chunk.chunk_id,
                                }
                            ),
                            document_revision=f"version:{version}:sha256:{digest}",
                            source_name="Handover evidence",
                            source_ref=chunk.source_ref,
                            locator=str(chunk.metadata["locator"]),
                            chunk_id=chunk.chunk_id,
                            text=chunk.text,
                            content_digest="sha256:"
                            + hashlib.sha256(chunk.text.encode()).hexdigest(),
                            score=chunk.score,
                        )
                        key = (excerpt.document_revision, excerpt.chunk_id)
                        if key in excerpts and excerpts[key] != excerpt:
                            raise ValueError(
                                "Core handover retrieval has conflicting chunk evidence"
                            )
                        excerpts[key] = excerpt
            return GovernedDocumentCollection(
                excerpts=tuple(
                    sorted(
                        excerpts.values(),
                        key=lambda item: (-item.score, item.document_revision, item.chunk_id),
                    )[:limit]
                ),
                observed_at=self.clock(),
                complete=False,
                limitation="handover_index_completeness_unverified",
                index_generation="handover:" + content_digest({"sources": sources}),
                access_scope_digest=content_digest(
                    {"principal_ref": principal_ref, "sources": sources}
                ),
                retrieval_mode="lexical",
            )


@dataclass(frozen=True, slots=True)
class CombinedGovernedHandoverReader:
    """Preserve the independent existing document source alongside explicit handover evidence."""

    handover: CoreHandoverDocumentReader
    existing: GovernedDocumentReader | None

    async def search(
        self,
        *,
        query: str,
        principal_ref: str,
        principal_role: CeilingRole,
        principal_groups: frozenset[str],
        purpose: str,
        limit: int,
        target: Applicability | None = None,
        exact_refs: tuple[str, ...] = (),
        context_source: str | None = None,
        conversation_ref: str | None = None,
        document_context_digest: str | None = None,
    ) -> GovernedDocumentCollection:
        """Combine ordinary authorized reads; exact context stays with its original source.

        Target or document-context selectors never widen into subject-wide handover search.
        The scoped reader's authorization failure propagates without a fallback or added excerpt.
        """
        if (
            target is not None
            or exact_refs
            or context_source is not None
            or conversation_ref is not None
            or document_context_digest is not None
        ):
            if self.existing is None:
                raise PermissionError("scoped document reader is unavailable")
            return await self.existing.search(
                query=query,
                principal_ref=principal_ref,
                principal_role=principal_role,
                principal_groups=principal_groups,
                purpose=purpose,
                limit=limit,
                target=target,
                exact_refs=exact_refs,
                context_source=context_source,
                conversation_ref=conversation_ref,
                document_context_digest=document_context_digest,
            )
        handover = await self.handover.search(
            query=query,
            principal_ref=principal_ref,
            principal_role=principal_role,
            principal_groups=principal_groups,
            purpose=purpose,
            limit=limit,
        )
        if self.existing is None:
            return handover
        existing = await self.existing.search(
            query=query,
            principal_ref=principal_ref,
            principal_role=principal_role,
            principal_groups=principal_groups,
            purpose=purpose,
            limit=limit,
        )
        excerpts = {(item.document_revision, item.chunk_id): item for item in existing.excerpts}
        for item in handover.excerpts:
            key = item.document_revision, item.chunk_id
            prior = excerpts.get(key)
            if prior is not None and (
                prior.text != item.text
                or prior.source_ref != item.source_ref
                or prior.locator != item.locator
            ):
                raise ValueError("governed document readers disagree on immutable source content")
            if prior is None:
                excerpts[key] = item
        return GovernedDocumentCollection(
            excerpts=tuple(
                sorted(
                    excerpts.values(),
                    key=lambda item: (-item.score, item.document_revision, item.chunk_id),
                )[:limit]
            ),
            observed_at=min(handover.observed_at, existing.observed_at),
            complete=False,
            limitation="handover_index_completeness_unverified",
            index_generation="combined:"
            + content_digest(
                {
                    "handover": handover.index_generation,
                    "existing": existing.index_generation,
                }
            ),
            access_scope_digest=content_digest(
                {
                    "handover": handover.access_scope_digest,
                    "existing": existing.access_scope_digest,
                }
            ),
            retrieval_mode=existing.retrieval_mode,
        )


__all__ = ["CombinedGovernedHandoverReader", "CoreHandoverDocumentReader"]
