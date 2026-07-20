from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.operator_memory import (
    InMemoryOperatorMemoryProposalStore,
    InMemoryOperatorMemoryStore,
    MemoryCategory,
    OperatorMemoryProposalError,
    OperatorMemoryProposalState,
    OperatorMemoryProposalWorkshop,
    ScopeKind,
)

_NOW = datetime(2026, 7, 20, tzinfo=UTC)


class _Audit:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def append(self, event: object) -> None:
        self.events.append(event)


class _Authorizer:
    def can_review(self, reviewer_id: str) -> bool:
        return reviewer_id.startswith("reviewer-") or reviewer_id == "Norns"


def _workshop() -> tuple[OperatorMemoryProposalWorkshop, InMemoryOperatorMemoryStore]:
    memory = InMemoryOperatorMemoryStore()
    return (
        OperatorMemoryProposalWorkshop(
            proposals=InMemoryOperatorMemoryProposalStore(),
            memory=memory,
            audit=_Audit(),  # type: ignore[arg-type]
            authorizer=_Authorizer(),
        ),
        memory,
    )


async def _proposal(workshop: OperatorMemoryProposalWorkshop) -> str:
    proposal = await workshop.propose(
        scope_kind=ScopeKind.RESOURCE,
        scope_ref="resource-hash-1",
        category=MemoryCategory.RUNBOOK_HINT,
        body="Use the scoped query before escalation.",
        evidence_refs=("audit:1",),
        proposed_by_agent="Norns",
        at=_NOW,
    )
    return proposal.proposal_id


async def test_draft_is_inert_until_independent_review_and_materialization() -> None:
    workshop, memory = _workshop()
    proposal_id = await _proposal(workshop)

    assert await memory.list_for_review(limit=100) == ()
    reviewed = await workshop.review(
        proposal_id,
        reviewer_id="reviewer-1",
        approve=True,
        reason="Evidence supports this bounded note.",
        at=_NOW,
    )
    assert reviewed.state is OperatorMemoryProposalState.APPROVED
    assert await memory.list_for_review(limit=100) == ()

    entry = await workshop.materialize(proposal_id, actor_id="reviewer-1", at=_NOW)

    assert entry.approved_by == "reviewer-1"
    assert entry.author == "Norns"
    assert len(await memory.list_for_review(limit=100)) == 1


async def test_proposer_cannot_self_review() -> None:
    workshop, _ = _workshop()
    proposal_id = await _proposal(workshop)

    with pytest.raises(OperatorMemoryProposalError, match="self-review"):
        await workshop.review(
            proposal_id,
            reviewer_id="Norns",
            approve=True,
            reason="Self approval is forbidden.",
            at=_NOW,
        )


async def test_rejected_proposal_cannot_materialize() -> None:
    workshop, _ = _workshop()
    proposal_id = await _proposal(workshop)
    await workshop.review(
        proposal_id,
        reviewer_id="reviewer-1",
        approve=False,
        reason="The evidence is too narrow.",
        at=_NOW,
    )

    with pytest.raises(OperatorMemoryProposalError, match="only an approved"):
        await workshop.materialize(proposal_id, actor_id="reviewer-1", at=_NOW)
