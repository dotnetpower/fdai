"""Reviewed, grounded, and reversible operator-memory compaction workflow."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from fdai.core.operator_memory.sanitizer import detect_injection_markers
from fdai.core.operator_memory.store import _reject_policy_violations
from fdai.core.operator_memory.types import (
    MemoryCategory,
    MemorySource,
    OperatorMemoryEntry,
    ScopeKind,
)


class MemoryCompactionState(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True, slots=True)
class MemoryCompactionCandidate:
    candidate_id: str
    scope_kind: str
    scope_ref: str
    category: str
    body: str
    source_entry_ids: tuple[UUID, ...]
    source_refs: tuple[str, ...]
    proposed_by_agent: str
    created_at: datetime
    state: MemoryCompactionState = MemoryCompactionState.DRAFT
    reviewed_by: str | None = None
    review_reason: str | None = None
    reviewed_at: datetime | None = None
    promoted_entry_id: UUID | None = None


class MemoryCompactionRepository(Protocol):
    async def create(self, candidate: MemoryCompactionCandidate) -> MemoryCompactionCandidate: ...

    async def get(self, candidate_id: str) -> MemoryCompactionCandidate: ...

    async def list(self, *, limit: int) -> tuple[MemoryCompactionCandidate, ...]: ...

    async def transition(
        self,
        candidate: MemoryCompactionCandidate,
        *,
        expected_state: MemoryCompactionState,
    ) -> MemoryCompactionCandidate | None: ...

    async def promote(
        self,
        candidate: MemoryCompactionCandidate,
        entry: OperatorMemoryEntry,
        *,
        expected_state: MemoryCompactionState,
    ) -> MemoryCompactionCandidate | None: ...

    async def rollback(
        self,
        candidate: MemoryCompactionCandidate,
        *,
        expected_state: MemoryCompactionState,
    ) -> MemoryCompactionCandidate | None: ...


class MemoryCompactionAuthorizer(Protocol):
    def can_review(self, actor_id: str) -> bool: ...


class MemoryCompactionError(ValueError):
    """Compaction proposal, review, promotion, or rollback failed closed."""


class InMemoryMemoryCompactionRepository:
    def __init__(self) -> None:
        self.candidates: dict[str, MemoryCompactionCandidate] = {}
        self.promoted_entries: dict[UUID, OperatorMemoryEntry] = {}
        self.inactive_promoted_entries: set[UUID] = set()
        self.superseded_sources: set[UUID] = set()

    async def create(
        self,
        candidate: MemoryCompactionCandidate,
    ) -> MemoryCompactionCandidate:
        existing = self.candidates.get(candidate.candidate_id)
        if existing is not None:
            return existing
        self.candidates[candidate.candidate_id] = candidate
        return candidate

    async def get(self, candidate_id: str) -> MemoryCompactionCandidate:
        try:
            return self.candidates[candidate_id]
        except KeyError as exc:
            raise MemoryCompactionError("memory compaction candidate was not found") from exc

    async def list(self, *, limit: int) -> tuple[MemoryCompactionCandidate, ...]:
        if not 1 <= limit <= 200:
            raise ValueError("memory compaction review limit MUST be in [1, 200]")
        return tuple(
            sorted(
                self.candidates.values(),
                key=lambda candidate: (candidate.created_at, candidate.candidate_id),
                reverse=True,
            )[:limit]
        )

    async def transition(
        self,
        candidate: MemoryCompactionCandidate,
        *,
        expected_state: MemoryCompactionState,
    ) -> MemoryCompactionCandidate | None:
        current = await self.get(candidate.candidate_id)
        if current.state is not expected_state:
            return None
        self.candidates[candidate.candidate_id] = candidate
        return candidate

    async def promote(
        self,
        candidate: MemoryCompactionCandidate,
        entry: OperatorMemoryEntry,
        *,
        expected_state: MemoryCompactionState,
    ) -> MemoryCompactionCandidate | None:
        current = await self.get(candidate.candidate_id)
        if current.state is not expected_state:
            return None
        promoted = replace(
            candidate,
            state=MemoryCompactionState.PROMOTED,
            promoted_entry_id=entry.id,
        )
        self.promoted_entries[entry.id] = entry
        self.superseded_sources.update(candidate.source_entry_ids)
        self.candidates[candidate.candidate_id] = promoted
        return promoted

    async def rollback(
        self,
        candidate: MemoryCompactionCandidate,
        *,
        expected_state: MemoryCompactionState,
    ) -> MemoryCompactionCandidate | None:
        current = await self.get(candidate.candidate_id)
        if current.state is not expected_state or current.promoted_entry_id is None:
            return None
        self.inactive_promoted_entries.add(current.promoted_entry_id)
        self.superseded_sources.difference_update(current.source_entry_ids)
        rolled_back = replace(current, state=MemoryCompactionState.ROLLED_BACK)
        self.candidates[candidate.candidate_id] = rolled_back
        return rolled_back


class MemoryCompactionService:
    def __init__(
        self,
        *,
        repository: MemoryCompactionRepository,
        authorizer: MemoryCompactionAuthorizer,
    ) -> None:
        self._repository = repository
        self._authorizer = authorizer

    async def propose(
        self,
        sources: Sequence[OperatorMemoryEntry],
        *,
        body: str,
        proposed_by_agent: str,
        at: datetime,
    ) -> MemoryCompactionCandidate:
        if len(sources) < 2:
            raise MemoryCompactionError("memory compaction requires at least two source entries")
        if not proposed_by_agent:
            raise MemoryCompactionError("memory compaction proposer MUST be non-empty")
        if not body.strip() or detect_injection_markers(body):
            raise MemoryCompactionError("memory compaction body is empty or unsafe")
        first = sources[0]
        if any(source.superseded_by is not None for source in sources):
            raise MemoryCompactionError("memory compaction sources MUST be active")
        if any(
            source.scope_kind is not first.scope_kind
            or source.scope_ref != first.scope_ref
            or source.category is not first.category
            for source in sources
        ):
            raise MemoryCompactionError("memory compaction sources MUST share scope and category")
        source_ids = tuple(sorted({source.id for source in sources}, key=str))
        if len(source_ids) != len(sources):
            raise MemoryCompactionError("memory compaction sources MUST be unique")
        source_refs = tuple(source.source_ref for source in sources)
        if any(not source_ref for source_ref in source_refs):
            raise MemoryCompactionError("memory compaction sources MUST have provenance refs")
        candidate_id = (
            "memory-compaction:"
            + hashlib.sha256(
                "\0".join((proposed_by_agent, body, *(str(value) for value in source_ids))).encode()
            ).hexdigest()[:32]
        )
        return await self._repository.create(
            MemoryCompactionCandidate(
                candidate_id=candidate_id,
                scope_kind=first.scope_kind.value,
                scope_ref=first.scope_ref,
                category=first.category.value,
                body=body,
                source_entry_ids=source_ids,
                source_refs=source_refs,
                proposed_by_agent=proposed_by_agent,
                created_at=at,
            )
        )

    async def review(
        self,
        candidate_id: str,
        *,
        reviewer_id: str,
        approve: bool,
        reason: str,
        at: datetime,
    ) -> MemoryCompactionCandidate:
        current = await self._repository.get(candidate_id)
        if current.state is not MemoryCompactionState.DRAFT:
            raise MemoryCompactionError("only a draft memory compaction can be reviewed")
        if not self._authorizer.can_review(reviewer_id) or not reason.strip():
            raise MemoryCompactionError(
                "memory compaction review requires authorization and reason"
            )
        if reviewer_id == current.proposed_by_agent:
            raise MemoryCompactionError("memory compaction proposer cannot self-review")
        state = MemoryCompactionState.APPROVED if approve else MemoryCompactionState.REJECTED
        reviewed = await self._repository.transition(
            replace(
                current,
                state=state,
                reviewed_by=reviewer_id,
                review_reason=reason.strip(),
                reviewed_at=at,
            ),
            expected_state=MemoryCompactionState.DRAFT,
        )
        if reviewed is None:
            raise MemoryCompactionError("memory compaction changed before review")
        return reviewed

    async def promote(
        self,
        candidate_id: str,
        *,
        actor_id: str,
        at: datetime,
    ) -> MemoryCompactionCandidate:
        current = await self._repository.get(candidate_id)
        if current.state is not MemoryCompactionState.APPROVED or current.reviewed_by is None:
            raise MemoryCompactionError("only an approved memory compaction can be promoted")
        if not self._authorizer.can_review(actor_id):
            raise MemoryCompactionError("actor is not authorized to promote memory compaction")
        entry = OperatorMemoryEntry(
            id=uuid4(),
            scope_kind=ScopeKind(current.scope_kind),
            scope_ref=current.scope_ref,
            category=MemoryCategory(current.category),
            body=current.body,
            source_event=MemorySource.MEMORY_COMPACTION,
            source_ref=current.candidate_id,
            author=f"memory-compactor:{current.proposed_by_agent}",
            approved_by=current.reviewed_by,
            created_at=at,
        )
        _reject_policy_violations(entry)
        promoted = await self._repository.promote(
            current,
            entry,
            expected_state=MemoryCompactionState.APPROVED,
        )
        if promoted is None:
            raise MemoryCompactionError("memory compaction changed before promotion")
        return promoted

    async def rollback(self, candidate_id: str, *, actor_id: str) -> MemoryCompactionCandidate:
        current = await self._repository.get(candidate_id)
        if not self._authorizer.can_review(actor_id):
            raise MemoryCompactionError("actor is not authorized to roll back memory compaction")
        rolled_back = await self._repository.rollback(
            current,
            expected_state=MemoryCompactionState.PROMOTED,
        )
        if rolled_back is None:
            raise MemoryCompactionError("only a promoted memory compaction can be rolled back")
        return rolled_back


__all__ = [
    "InMemoryMemoryCompactionRepository",
    "MemoryCompactionAuthorizer",
    "MemoryCompactionCandidate",
    "MemoryCompactionError",
    "MemoryCompactionRepository",
    "MemoryCompactionService",
    "MemoryCompactionState",
]
