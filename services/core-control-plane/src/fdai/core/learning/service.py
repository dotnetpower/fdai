"""Off-path orchestration for inert post-turn improvement proposals."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from fdai.core.learning.eligibility import PostTurnEligibilityPolicy
from fdai.core.learning.ledger import (
    PostTurnReviewLedger,
    PostTurnReviewRecord,
    PostTurnReviewState,
    pending_record,
)
from fdai.core.learning.metrics import PostTurnReviewMetrics
from fdai.core.learning.models import (
    NoImprovement,
    PostTurnProposal,
    PostTurnReviewInput,
)


class PostTurnReviewer(Protocol):
    async def review(
        self,
        review_input: PostTurnReviewInput,
    ) -> PostTurnProposal | NoImprovement: ...


class PostTurnProposalRouter(Protocol):
    async def route(
        self,
        proposal: PostTurnProposal,
        *,
        proposed_by: str,
        at: datetime,
    ) -> str: ...


class NoOpPostTurnReviewer:
    async def review(self, review_input: PostTurnReviewInput) -> NoImprovement:  # noqa: ARG002
        return NoImprovement(reason="reviewer_unavailable")


class PostTurnReviewCoordinator:
    """Evaluate, deduplicate, and route a completed turn without raising."""

    def __init__(
        self,
        *,
        eligibility: PostTurnEligibilityPolicy,
        reviewer: PostTurnReviewer,
        router: PostTurnProposalRouter,
        ledger: PostTurnReviewLedger,
        metrics: PostTurnReviewMetrics | None = None,
        now: Callable[[], datetime],
        proposed_by: str = "Norns",
    ) -> None:
        self._eligibility = eligibility
        self._reviewer = reviewer
        self._router = router
        self._ledger = ledger
        self._metrics = metrics or PostTurnReviewMetrics()
        self._now = now
        self._proposed_by = proposed_by

    @property
    def metrics(self) -> PostTurnReviewMetrics:
        return self._metrics

    async def review(self, review_input: PostTurnReviewInput) -> PostTurnReviewRecord:
        decision = self._eligibility.evaluate(review_input)
        started, created = await self._ledger.start(
            pending_record(
                review_id=review_input.review_id,
                principal_scope=review_input.principal_scope,
                reasons=decision.reasons,
                at=review_input.completed_at,
            )
        )
        if not created:
            self._metrics.increment("duplicates")
            return started
        if not decision.eligible:
            self._metrics.increment("ineligible")
            return await self._ledger.finish(
                review_input.review_id,
                state=PostTurnReviewState.INELIGIBLE,
                reasons=tuple(reason.value for reason in decision.reasons),
                updated_at=self._now(),
            )

        self._metrics.increment("eligible")
        try:
            proposal = await self._reviewer.review(review_input)
        except Exception as exc:  # noqa: BLE001 - off-path failure is a terminal ledger state
            self._metrics.increment("failed")
            return await self._ledger.finish(
                review_input.review_id,
                state=PostTurnReviewState.FAILED,
                reasons=(f"reviewer_error:{type(exc).__name__}",),
                updated_at=self._now(),
            )
        if isinstance(proposal, NoImprovement):
            self._metrics.increment("abstained")
            return await self._ledger.finish(
                review_input.review_id,
                state=PostTurnReviewState.ABSTAINED,
                reasons=(proposal.reason,),
                updated_at=self._now(),
            )

        dedup_key = proposal_dedup_key(review_input, proposal)
        if not await self._ledger.reserve_proposal(
            review_id=review_input.review_id,
            dedup_key=dedup_key,
        ):
            self._metrics.increment("duplicates")
            return await self._ledger.finish(
                review_input.review_id,
                state=PostTurnReviewState.DUPLICATE,
                reasons=("duplicate_proposal",),
                updated_at=self._now(),
                proposal_kind=proposal.kind,
                dedup_key=dedup_key,
            )
        try:
            proposal_ref = await self._router.route(
                proposal,
                proposed_by=self._proposed_by,
                at=self._now(),
            )
        except Exception as exc:  # noqa: BLE001 - off-path failure is a terminal ledger state
            self._metrics.increment("failed")
            return await self._ledger.finish(
                review_input.review_id,
                state=PostTurnReviewState.FAILED,
                reasons=(f"router_error:{type(exc).__name__}",),
                updated_at=self._now(),
                proposal_kind=proposal.kind,
                dedup_key=dedup_key,
            )
        self._metrics.increment("routed")
        return await self._ledger.finish(
            review_input.review_id,
            state=PostTurnReviewState.ROUTED,
            reasons=("proposal_routed",),
            updated_at=self._now(),
            proposal_kind=proposal.kind,
            proposal_ref=proposal_ref,
            dedup_key=dedup_key,
        )


def proposal_dedup_key(
    review_input: PostTurnReviewInput,
    proposal: PostTurnProposal,
) -> str:
    fingerprint = review_input.procedure_fingerprint or _derived_fingerprint(review_input)
    evidence_digest = hashlib.sha256(
        json.dumps(
            {
                "assistant_turn_id": review_input.assistant_turn_id,
                "evidence_refs": sorted({*review_input.evidence_refs, *proposal.evidence_refs}),
                "operator_turn_id": review_input.operator_turn_id,
                "tool_evidence_refs": sorted(
                    receipt.evidence_ref for receipt in review_input.tool_receipts
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    material = "\0".join(
        (review_input.principal_scope, proposal.kind.value, fingerprint, evidence_digest)
    )
    return "post-turn-proposal:" + hashlib.sha256(material.encode()).hexdigest()


def _derived_fingerprint(review_input: PostTurnReviewInput) -> str:
    material = {
        "corrections": [_normalize(value) for value in review_input.explicit_corrections],
        "outcomes": sorted(review_input.validation_outcomes),
        "tools": sorted(
            (receipt.tool_name, receipt.status) for receipt in review_input.tool_receipts
        ),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


__all__ = [
    "NoOpPostTurnReviewer",
    "PostTurnProposalRouter",
    "PostTurnReviewCoordinator",
    "PostTurnReviewer",
    "proposal_dedup_key",
]
