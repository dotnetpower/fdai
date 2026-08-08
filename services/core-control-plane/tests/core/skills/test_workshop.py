"""Audited runtime skill proposal workflow tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.core.skills import (
    InMemorySkillProposalStore,
    RuntimeSkill,
    SkillCatalog,
    SkillProposalState,
    SkillWorkshop,
    SkillWorkshopError,
    skill_body_digest,
)

_NOW = datetime(2026, 7, 17, 4, 0, tzinfo=UTC)


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def append(self, event: dict[str, Any]) -> None:
        self.events.append(dict(event))


class _Authorizer:
    def can_review(self, reviewer_id: str) -> bool:
        return reviewer_id.startswith("owner-")


class _Verifier:
    def __init__(self, trusted: bool = True) -> None:
        self.trusted = trusted

    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return self.trusted


def _skill() -> bytes:
    body = "Use query_inventory and cite every returned resource reference."
    return f"""---
name: inventory-citations
version: 1.0.0
description: Collect inventory citations.
source: source:inventory-citations
body_sha256: "{skill_body_digest(body)}"
required_tools: [query_inventory]
allowed_agents: [Bragi]
---
{body}
""".encode()


def _workshop() -> tuple[SkillWorkshop, _Audit]:
    audit = _Audit()
    return (
        SkillWorkshop(
            store=InMemorySkillProposalStore(),
            audit=audit,
            authorizer=_Authorizer(),
        ),
        audit,
    )


async def test_propose_review_materialize_is_audited_and_inert() -> None:
    workshop, audit = _workshop()
    proposal = await workshop.propose(_skill(), proposed_by_agent="Bragi", at=_NOW)
    approved = await workshop.review(
        proposal.proposal_id,
        reviewer_id="owner-1",
        approve=True,
        reason="Verified bounded tool usage.",
        at=_NOW,
    )
    markdown = await workshop.materialize(
        proposal.proposal_id,
        actor_id="owner-1",
        at=_NOW,
    )

    assert approved.state is SkillProposalState.APPROVED
    assert markdown == _skill()
    assert [event["action_kind"] for event in audit.events] == [
        "skill.proposed",
        "skill.approved",
        "skill.materialized",
    ]
    assert all("markdown" not in event for event in audit.events)


async def test_unauthorized_or_self_review_is_blocked() -> None:
    workshop, _ = _workshop()
    proposal = await workshop.propose(_skill(), proposed_by_agent="Bragi", at=_NOW)

    with pytest.raises(SkillWorkshopError, match="not authorized"):
        await workshop.review(
            proposal.proposal_id,
            reviewer_id="reader-1",
            approve=True,
            reason="No authority.",
            at=_NOW,
        )
    owner_proposal = await workshop.propose(
        _skill(),
        proposed_by_agent="owner-agent",
        at=_NOW,
    )
    with pytest.raises(SkillWorkshopError, match="self-review"):
        await workshop.review(
            owner_proposal.proposal_id,
            reviewer_id="owner-agent",
            approve=True,
            reason="Self review.",
            at=_NOW,
        )


async def test_rejected_proposal_cannot_materialize_or_review_twice() -> None:
    workshop, audit = _workshop()
    proposal = await workshop.propose(_skill(), proposed_by_agent="Bragi", at=_NOW)
    await workshop.review(
        proposal.proposal_id,
        reviewer_id="owner-1",
        approve=False,
        reason="Needs narrower instructions.",
        at=_NOW,
    )

    with pytest.raises(SkillWorkshopError, match="approved"):
        await workshop.materialize(proposal.proposal_id, actor_id="owner-1", at=_NOW)
    with pytest.raises(SkillWorkshopError, match="draft"):
        await workshop.review(
            proposal.proposal_id,
            reviewer_id="owner-1",
            approve=True,
            reason="Changed mind.",
            at=_NOW,
        )
    assert audit.events[-1]["action_kind"] == "skill.rejected"


async def test_identical_agent_proposal_is_deduplicated() -> None:
    workshop, audit = _workshop()
    first = await workshop.propose(_skill(), proposed_by_agent="Bragi", at=_NOW)
    second = await workshop.propose(_skill(), proposed_by_agent="Bragi", at=_NOW)

    assert first.proposal_id == second.proposal_id
    assert len(audit.events) == 2


async def test_promotion_rechecks_trust_and_installs_disabled() -> None:
    workshop, audit = _workshop()
    proposal = await workshop.propose(_skill(), proposed_by_agent="Bragi", at=_NOW)
    await workshop.review(
        proposal.proposal_id,
        reviewer_id="owner-1",
        approve=True,
        reason="Verified bounded instructions.",
        at=_NOW,
    )

    with pytest.raises(SkillWorkshopError, match="trust"):
        await workshop.promote(
            proposal.proposal_id,
            actor_id="owner-1",
            at=_NOW,
            catalog=SkillCatalog(),
            verifier=_Verifier(False),
        )
    promoted = await workshop.promote(
        proposal.proposal_id,
        actor_id="owner-1",
        at=_NOW,
        catalog=SkillCatalog(),
        verifier=_Verifier(),
    )

    assert promoted.get("inventory-citations").enabled is False
    assert audit.events[-1]["action_kind"] == "skill.promoted"
