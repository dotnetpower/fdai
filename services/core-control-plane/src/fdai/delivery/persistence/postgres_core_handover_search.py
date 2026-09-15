"""Exact-goal PostgreSQL chunk search without raw knowledge/document-table access."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fdai_service_contracts import KnowledgeChunk

from fdai.core.human_assignment.goals import HandoverGoal, HandoverGoalService
from fdai.delivery.persistence.postgres_handover_admission import PostgresHandoverSourceReader


@dataclass(frozen=True, slots=True)
class PostgresCoreHandoverSearch:
    """Bind every content query to a current independently checked Core goal snapshot.

    Caller access labels narrow an already subject-owned document join. They cannot
    select another uploader, goal, collection, source version, or an inactive index.
    """

    source: PostgresHandoverSourceReader
    goals: HandoverGoalService
    goal: HandoverGoal

    async def search(
        self,
        query: str,
        *,
        collection_id: str,
        allowed_access_refs: frozenset[str],
        k: int = 5,
    ) -> tuple[KnowledgeChunk, ...]:
        """Return bounded real chunk text after admission and before exact post-read fencing."""
        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query) > 20_000
            or not isinstance(collection_id, str)
            or not 1 <= len(collection_id) <= 256
            or not isinstance(allowed_access_refs, frozenset)
            or not 1 <= len(allowed_access_refs) <= 100
            or any(
                not isinstance(ref, str) or not 1 <= len(ref) <= 512 for ref in allowed_access_refs
            )
            or type(k) is not int
            or not 1 <= k <= 20
        ):
            raise ValueError("Core handover search requires bounded exact query and access inputs")
        async with asyncio.timeout(30):
            current = await self.goals.get_goal(self.goal.goal_id)
            if current != self.goal:
                raise ValueError("Core handover search goal changed before admission")
            await self.goals.require_current_evidence(current)
            statement = "SELECT * FROM fdai_search_core_handover_goal(%s,%s,%s,%s,%s,%s,%s)"
            parameters = (
                current.goal_id,
                current.revision,
                current.subject_ref,
                collection_id,
                sorted(allowed_access_refs),
                query,
                k,
            )
            async with await self.source._connect() as connection:
                rows = await (
                    await connection.execute(
                        statement,
                        parameters,
                    )
                ).fetchall()
            if await self.goals.get_goal(current.goal_id) != current:
                raise ValueError("Core handover search goal changed during content read")
            await self.goals.require_current_evidence(current)
            async with await self.source._connect() as connection:
                latest = await (await connection.execute(statement, parameters)).fetchall()
            if latest != rows:
                raise ValueError("Core handover search chunks changed during source verification")
            return tuple(
                KnowledgeChunk(
                    doc_id=row["doc_id"],
                    chunk_id=row["chunk_id"],
                    text=row["text"],
                    source_ref=row["source_ref"],
                    metadata=row["metadata"],
                    score=float(row["score"]),
                )
                for row in rows
            )


__all__ = ["PostgresCoreHandoverSearch"]
