"""Read-only evidence checks for inert handover candidates, with no human or catalog authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai_service_contracts.handover_checklist import checklist_complete, project_checklist
from fdai_service_contracts.handover_knowledge import (
    HandoverKnowledgeDecision,
    HandoverKnowledgeNotice,
    knowledge_source_digest,
)


class HandoverKnowledgeSourceReader(Protocol):
    """Read exact same-venue source metadata; no stage writes, raw content, or promotion port."""

    async def read(self, notice: HandoverKnowledgeNotice) -> Mapping[str, Any] | None: ...

    async def contribution_current(self, notice: HandoverKnowledgeNotice) -> bool: ...

    async def document_admitted(
        self, notice: HandoverKnowledgeNotice, *, evidence_ref: str, digest: str
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class HandoverKnowledgeSourceCheck:
    """Forseti's independent source checks, also reused read-only before each owner materializes."""

    reader: HandoverKnowledgeSourceReader
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def check(self, notice: HandoverKnowledgeNotice) -> HandoverKnowledgeDecision:
        """Hold unavailable/corrupt evidence; only authoritative absence withdraws a source."""
        notice.require_current(self.clock())
        record = await self.reader.read(notice)
        if record is None:
            return _decision(notice, "withdrawn", "source_withdrawn")
        if record.get("goal_id") != notice.goal_id or type(record.get("revision")) is not int:
            return _decision(notice, "held", "source_changed")
        if (
            record["revision"] != notice.goal_revision
            or knowledge_source_digest(record) != notice.source_digest
        ):
            return _decision(notice, "held", "source_changed")
        if record.get("state") in {"stale", "declined", "superseded"}:
            return _decision(notice, "withdrawn", "source_withdrawn")
        evidence = record.get("evidence", [])
        if not isinstance(evidence, list) or len(evidence) > 64:
            return _decision(notice, "held", "source_unavailable")
        claims: dict[str, str] = {}
        for item in evidence:
            if not isinstance(item, Mapping):
                return _decision(notice, "held", "source_unavailable")
            ref, digest = item.get("evidence_ref"), item.get("digest")
            if isinstance(ref, str) and isinstance(digest, str):
                if ref in claims and claims[ref] != digest:
                    return _decision(notice, "conflict", "evidence_conflict")
                claims[ref] = digest
        try:
            goal = project_checklist(record)
            complete = checklist_complete(goal)
        except (TypeError, ValueError):
            return _decision(notice, "held", "source_unavailable")
        if not complete or goal.get("state") not in {"ready_for_review", "accepted"} or not claims:
            return _decision(notice, "gap", "checklist_incomplete")
        if not await self.reader.contribution_current(notice):
            return _decision(notice, "withdrawn", "source_withdrawn")
        for ref, digest in claims.items():
            if not await self.reader.document_admitted(notice, evidence_ref=ref, digest=digest):
                return _decision(notice, "withdrawn", "source_withdrawn")
        notice.require_current(self.clock())
        # Recheck the source after potentially slow document I/O. Do not seal an obsolete goal.
        final = await self.reader.read(notice)
        if final is None:
            return _decision(notice, "withdrawn", "source_withdrawn")
        if knowledge_source_digest(final) != notice.source_digest:
            return _decision(notice, "held", "source_changed")
        if not await self.reader.contribution_current(notice):
            return _decision(notice, "withdrawn", "source_withdrawn")
        return HandoverKnowledgeDecision(
            notice=notice,
            disposition="admitted",
            reason="source_admitted",
            evidence_refs=tuple(sorted(claims)),
            evidence_digests=tuple(claims[ref] for ref in sorted(claims)),
        )


def _decision(
    notice: HandoverKnowledgeNotice, disposition: str, reason: str
) -> HandoverKnowledgeDecision:
    return HandoverKnowledgeDecision.model_validate(
        {"notice": notice, "disposition": disposition, "reason": reason}
    )


__all__ = ["HandoverKnowledgeSourceCheck", "HandoverKnowledgeSourceReader"]
