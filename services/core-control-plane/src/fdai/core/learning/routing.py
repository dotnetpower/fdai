"""Proposal routing into existing governed owner workflows."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from fdai.core.learning.models import (
    OperatorMemoryCandidate,
    PostTurnProposal,
    RuleCandidateHint,
    SkillProposalDraft,
)
from fdai.core.operator_memory.proposals import OperatorMemoryProposalWorkshop
from fdai.core.skills.workshop import SkillWorkshop


class RuleHintSubmitter(Protocol):
    async def submit_rule_hint(
        self,
        hint: RuleCandidateHint,
        *,
        proposed_by: str,
        at: datetime,
    ) -> str: ...


class GovernedPostTurnProposalRouter:
    """Delegate proposal persistence to the subsystem that owns each artifact."""

    def __init__(
        self,
        *,
        operator_memory: OperatorMemoryProposalWorkshop,
        skills: SkillWorkshop,
        rule_hints: RuleHintSubmitter,
    ) -> None:
        self._operator_memory = operator_memory
        self._skills = skills
        self._rule_hints = rule_hints

    async def route(
        self,
        proposal: PostTurnProposal,
        *,
        proposed_by: str,
        at: datetime,
    ) -> str:
        if isinstance(proposal, OperatorMemoryCandidate):
            memory_proposal = await self._operator_memory.propose(
                scope_kind=proposal.scope_kind,
                scope_ref=proposal.scope_ref,
                category=proposal.category,
                body=proposal.body,
                evidence_refs=proposal.evidence_refs,
                proposed_by_agent=proposed_by,
                at=at,
            )
            return memory_proposal.proposal_id
        if isinstance(proposal, SkillProposalDraft):
            skill_proposal = await self._skills.propose(
                proposal.markdown,
                proposed_by_agent=proposed_by,
                at=at,
            )
            return skill_proposal.proposal_id
        return await self._rule_hints.submit_rule_hint(
            proposal,
            proposed_by=proposed_by,
            at=at,
        )


__all__ = ["GovernedPostTurnProposalRouter", "RuleHintSubmitter"]
