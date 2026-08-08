"""Reviewed draft workflow for post-turn operator-memory candidates."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid5

from fdai.core.operator_memory.store import OperatorMemoryStore
from fdai.core.operator_memory.types import (
    MemoryCategory,
    MemorySource,
    OperatorMemoryEntry,
    ScopeKind,
)

_PROPOSAL_NAMESPACE = UUID("00000000-0000-0000-0000-000000000037")


class OperatorMemoryProposalState(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    MATERIALIZED = "materialized"


@dataclass(frozen=True, slots=True)
class OperatorMemoryProposal:
    proposal_id: str
    content_hash: str
    scope_kind: ScopeKind
    scope_ref: str
    category: MemoryCategory
    body: str
    evidence_refs: tuple[str, ...]
    proposed_by_agent: str
    created_at: datetime
    state: OperatorMemoryProposalState = OperatorMemoryProposalState.DRAFT
    reviewed_by: str | None = None
    review_reason: str | None = None
    reviewed_at: datetime | None = None
    materialized_entry_id: UUID | None = None


class OperatorMemoryProposalStore(Protocol):
    async def create(self, proposal: OperatorMemoryProposal) -> OperatorMemoryProposal: ...

    async def get(self, proposal_id: str) -> OperatorMemoryProposal: ...

    async def transition(
        self,
        proposal: OperatorMemoryProposal,
        *,
        expected_state: OperatorMemoryProposalState,
    ) -> OperatorMemoryProposal | None: ...

    async def list(self) -> tuple[OperatorMemoryProposal, ...]: ...


class OperatorMemoryProposalAudit(Protocol):
    async def append(self, event: Mapping[str, Any]) -> None: ...


class OperatorMemoryProposalAuthorizer(Protocol):
    def can_review(self, reviewer_id: str) -> bool: ...


class OperatorMemoryProposalError(ValueError):
    """A proposal transition was invalid or unauthorized."""


class InMemoryOperatorMemoryProposalStore:
    def __init__(self) -> None:
        self._proposals: dict[str, OperatorMemoryProposal] = {}

    async def create(self, proposal: OperatorMemoryProposal) -> OperatorMemoryProposal:
        prior = self._proposals.get(proposal.proposal_id)
        if prior is not None:
            if prior.content_hash == proposal.content_hash:
                return prior
            raise OperatorMemoryProposalError("operator-memory proposal id collision")
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    async def get(self, proposal_id: str) -> OperatorMemoryProposal:
        try:
            return self._proposals[proposal_id]
        except KeyError as exc:
            raise OperatorMemoryProposalError(
                f"operator-memory proposal {proposal_id!r} was not found"
            ) from exc

    async def transition(
        self,
        proposal: OperatorMemoryProposal,
        *,
        expected_state: OperatorMemoryProposalState,
    ) -> OperatorMemoryProposal | None:
        current = await self.get(proposal.proposal_id)
        if current.state is not expected_state:
            return None
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    async def list(self) -> tuple[OperatorMemoryProposal, ...]:
        return tuple(self._proposals[key] for key in sorted(self._proposals))


class OperatorMemoryProposalWorkshop:
    """Stage, independently review, and materialize operator-memory drafts."""

    def __init__(
        self,
        *,
        proposals: OperatorMemoryProposalStore,
        memory: OperatorMemoryStore,
        audit: OperatorMemoryProposalAudit,
        authorizer: OperatorMemoryProposalAuthorizer,
    ) -> None:
        self._proposals = proposals
        self._memory = memory
        self._audit = audit
        self._authorizer = authorizer

    async def propose(
        self,
        *,
        scope_kind: ScopeKind,
        scope_ref: str,
        category: MemoryCategory,
        body: str,
        evidence_refs: tuple[str, ...],
        proposed_by_agent: str,
        at: datetime,
    ) -> OperatorMemoryProposal:
        if not proposed_by_agent.strip():
            raise OperatorMemoryProposalError("proposal agent MUST be non-empty")
        content_hash = _content_hash(
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            category=category,
            body=body,
            evidence_refs=evidence_refs,
        )
        proposal = await self._proposals.create(
            OperatorMemoryProposal(
                proposal_id=f"operator-memory-proposal:{content_hash[:32]}",
                content_hash=content_hash,
                scope_kind=scope_kind,
                scope_ref=scope_ref,
                category=category,
                body=body,
                evidence_refs=evidence_refs,
                proposed_by_agent=proposed_by_agent,
                created_at=at,
            )
        )
        await self._audit.append(_event("operator-memory.proposed", proposal, at=at))
        return proposal

    async def review(
        self,
        proposal_id: str,
        *,
        reviewer_id: str,
        approve: bool,
        reason: str,
        at: datetime,
    ) -> OperatorMemoryProposal:
        if not reviewer_id.strip() or not reason.strip():
            raise OperatorMemoryProposalError("proposal review requires reviewer and reason")
        if not self._authorizer.can_review(reviewer_id):
            raise OperatorMemoryProposalError("reviewer is not authorized")
        current = await self._proposals.get(proposal_id)
        if current.state is not OperatorMemoryProposalState.DRAFT:
            raise OperatorMemoryProposalError("only a draft proposal can be reviewed")
        if current.proposed_by_agent.strip().lower() == reviewer_id.strip().lower():
            raise OperatorMemoryProposalError("proposal agent cannot self-review")
        state = (
            OperatorMemoryProposalState.APPROVED
            if approve
            else OperatorMemoryProposalState.REJECTED
        )
        reviewed = await self._proposals.transition(
            replace(
                current,
                state=state,
                reviewed_by=reviewer_id,
                review_reason=reason.strip(),
                reviewed_at=at,
            ),
            expected_state=OperatorMemoryProposalState.DRAFT,
        )
        if reviewed is None:
            raise OperatorMemoryProposalError("proposal changed before review")
        await self._audit.append(_event(f"operator-memory.{state.value}", reviewed, at=at))
        return reviewed

    async def materialize(
        self,
        proposal_id: str,
        *,
        actor_id: str,
        at: datetime,
    ) -> OperatorMemoryEntry:
        current = await self._proposals.get(proposal_id)
        if current.state is not OperatorMemoryProposalState.APPROVED:
            raise OperatorMemoryProposalError("only an approved proposal can be materialized")
        if not self._authorizer.can_review(actor_id):
            raise OperatorMemoryProposalError("actor is not authorized")
        if current.reviewed_by is None:
            raise OperatorMemoryProposalError("approved proposal is missing its reviewer")
        entry_id = uuid5(_PROPOSAL_NAMESPACE, current.proposal_id)
        entry = await self._memory.append(
            OperatorMemoryEntry(
                id=entry_id,
                scope_kind=current.scope_kind,
                scope_ref=current.scope_ref,
                category=current.category,
                body=current.body,
                source_event=MemorySource.POST_TURN_REVIEW,
                source_ref=current.proposal_id,
                author=current.proposed_by_agent,
                approved_by=current.reviewed_by,
                created_at=at,
            )
        )
        materialized = await self._proposals.transition(
            replace(
                current,
                state=OperatorMemoryProposalState.MATERIALIZED,
                materialized_entry_id=entry.id,
            ),
            expected_state=OperatorMemoryProposalState.APPROVED,
        )
        if materialized is None:
            raise OperatorMemoryProposalError("proposal changed before materialization")
        await self._audit.append(_event("operator-memory.materialized", materialized, at=at))
        return entry


def _content_hash(
    *,
    scope_kind: ScopeKind,
    scope_ref: str,
    category: MemoryCategory,
    body: str,
    evidence_refs: tuple[str, ...],
) -> str:
    material = "\0".join(
        (scope_kind.value, scope_ref, category.value, body, *sorted(evidence_refs))
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _event(
    kind: str,
    proposal: OperatorMemoryProposal,
    *,
    at: datetime,
) -> dict[str, object]:
    return {
        "action_kind": kind,
        "proposal_id": proposal.proposal_id,
        "content_hash": proposal.content_hash,
        "state": proposal.state.value,
        "actor": proposal.reviewed_by or proposal.proposed_by_agent,
        "timestamp": at.isoformat(),
    }


__all__ = [
    "InMemoryOperatorMemoryProposalStore",
    "OperatorMemoryProposal",
    "OperatorMemoryProposalAudit",
    "OperatorMemoryProposalAuthorizer",
    "OperatorMemoryProposalError",
    "OperatorMemoryProposalState",
    "OperatorMemoryProposalStore",
    "OperatorMemoryProposalWorkshop",
]
