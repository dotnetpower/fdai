"""Mixed-family agreement and deterministic proposal verification."""

from __future__ import annotations

import asyncio
import re
from typing import Protocol

from fdai.core.learning.models import (
    NoImprovement,
    OperatorMemoryCandidate,
    PostTurnProposal,
    PostTurnReviewInput,
    RuleCandidateHint,
    SkillProposalDraft,
)
from fdai.core.operator_memory.sanitizer import detect_injection_markers
from fdai.core.skills import parse_skill_markdown

_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{12,}\b", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*", re.IGNORECASE),
    re.compile(r"(?:password|secret|token|api[_-]?key)\s*[:=]\s*\S+", re.IGNORECASE),
)


class PostTurnProposalModel(Protocol):
    @property
    def model_identity(self) -> str: ...

    @property
    def model_family(self) -> str: ...

    async def propose(
        self,
        review_input: PostTurnReviewInput,
    ) -> PostTurnProposal | NoImprovement: ...


class ConsensusPostTurnReviewer:
    """Accept only exact agreement from at least two distinct model families."""

    def __init__(self, models: tuple[PostTurnProposalModel, ...]) -> None:
        if len(models) < 2:
            raise ValueError("post-turn consensus requires at least two models")
        identities = {model.model_identity for model in models}
        families = {model.model_family for model in models}
        if len(identities) != len(models):
            raise ValueError("post-turn consensus model identities MUST be distinct")
        if len(families) != len(models):
            raise ValueError("post-turn consensus model families MUST be distinct")
        self._models = models

    async def review(
        self,
        review_input: PostTurnReviewInput,
    ) -> PostTurnProposal | NoImprovement:
        results = await asyncio.gather(*(model.propose(review_input) for model in self._models))
        if any(isinstance(result, NoImprovement) for result in results):
            return NoImprovement("model_abstained")
        proposals = tuple(result for result in results if not isinstance(result, NoImprovement))
        if not proposals or any(proposal != proposals[0] for proposal in proposals[1:]):
            return NoImprovement("model_disagreement")
        proposal = proposals[0]
        reason = _verification_failure(review_input, proposal)
        return NoImprovement(reason) if reason is not None else proposal


def _verification_failure(
    review_input: PostTurnReviewInput,
    proposal: PostTurnProposal,
) -> str | None:
    allowed_evidence = {
        *review_input.evidence_refs,
        *(receipt.evidence_ref for receipt in review_input.tool_receipts),
    }
    if not set(proposal.evidence_refs).issubset(allowed_evidence):
        return "unsupported_evidence"
    content = _proposal_content(proposal)
    if detect_injection_markers(content):
        return "unsafe_proposal"
    if any(pattern.search(content) for pattern in _SECRET_PATTERNS):
        return "secret_like_content"
    if isinstance(proposal, OperatorMemoryCandidate):
        if review_input.memory_scope_kind is None or review_input.memory_scope_ref is None:
            return "memory_scope_unavailable"
        if (
            proposal.scope_kind is not review_input.memory_scope_kind
            or proposal.scope_ref != review_input.memory_scope_ref
        ):
            return "memory_scope_mismatch"
    if isinstance(proposal, SkillProposalDraft):
        try:
            skill = parse_skill_markdown(proposal.markdown)
        except ValueError:
            return "invalid_skill_draft"
        if skill.manifest.name != proposal.skill_name:
            return "skill_name_mismatch"
    return None


def _proposal_content(proposal: PostTurnProposal) -> str:
    if isinstance(proposal, OperatorMemoryCandidate):
        return proposal.body
    if isinstance(proposal, SkillProposalDraft):
        try:
            return proposal.markdown.decode("utf-8")
        except UnicodeDecodeError:
            return "secret=invalid-utf8"
    if isinstance(proposal, RuleCandidateHint):
        return proposal.pattern
    raise TypeError(f"unsupported proposal type: {type(proposal).__name__}")


__all__ = ["ConsensusPostTurnReviewer", "PostTurnProposalModel"]
