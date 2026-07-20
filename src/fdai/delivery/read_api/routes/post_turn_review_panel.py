"""Read-only projection of post-turn review and proposal state."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from fdai.core.learning import PostTurnReviewLedger, PostTurnReviewMetrics
from fdai.core.operator_memory.proposals import OperatorMemoryProposalStore
from fdai.core.skills import SkillProposalStore
from fdai.delivery.read_api.routes.panels import PanelQueryError


class PostTurnReviewPanel:
    path = "/post-turn-reviews"
    name = "post-turn-reviews"

    def __init__(
        self,
        *,
        reviews: PostTurnReviewLedger,
        memory_proposals: OperatorMemoryProposalStore,
        skill_proposals: SkillProposalStore,
        metrics: PostTurnReviewMetrics,
        source: str,
        durable: bool,
    ) -> None:
        self._reviews = reviews
        self._memory_proposals = memory_proposals
        self._skill_proposals = skill_proposals
        self._metrics = metrics
        self._source = source
        self._durable = durable

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        try:
            limit = int(params.get("limit", "100"))
        except ValueError as exc:
            raise PanelQueryError("limit MUST be an integer") from exc
        if not 1 <= limit <= 200:
            raise PanelQueryError("limit MUST be in [1, 200]")
        all_reviews = await self._reviews.list()
        all_memory = await self._memory_proposals.list()
        all_skills = await self._skill_proposals.list()
        reviews = all_reviews[:limit]
        memory = all_memory[:limit]
        skills = all_skills[:limit]
        metrics = (
            _durable_metrics(all_reviews) if self._durable else asdict(self._metrics.snapshot())
        )
        proposal_types = Counter(
            item.proposal_kind.value for item in all_reviews if item.proposal_kind is not None
        )
        proposal_states = {
            "operator_memory": dict(Counter(item.state.value for item in all_memory)),
            "skill": dict(Counter(item.state.value for item in all_skills)),
        }
        reviewed = sum(
            count
            for states in proposal_states.values()
            for state, count in states.items()
            if state in {"approved", "rejected", "materialized"}
        )
        accepted = sum(
            count
            for states in proposal_states.values()
            for state, count in states.items()
            if state in {"approved", "materialized"}
        )
        return {
            "source": self._source,
            "durable": self._durable,
            "metrics": metrics,
            "proposal_types": dict(proposal_types),
            "proposal_states": proposal_states,
            "operator_acceptance_rate": accepted / reviewed if reviewed else None,
            "reviews": [
                {
                    "review_id": item.review_id,
                    "principal_scope": item.principal_scope,
                    "state": item.state.value,
                    "reasons": list(item.reasons),
                    "proposal_kind": (
                        item.proposal_kind.value if item.proposal_kind is not None else None
                    ),
                    "proposal_ref": item.proposal_ref,
                    "dedup_key": item.dedup_key,
                    "created_at": item.created_at.isoformat(),
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in reviews
            ],
            "operator_memory_proposals": [
                {
                    "proposal_id": item.proposal_id,
                    "scope_kind": item.scope_kind.value,
                    "scope_ref": item.scope_ref,
                    "category": item.category.value,
                    "evidence_refs": list(item.evidence_refs),
                    "proposed_by_agent": item.proposed_by_agent,
                    "state": item.state.value,
                    "reviewed_by": item.reviewed_by,
                    "review_reason": item.review_reason,
                    "materialized_entry_id": (
                        str(item.materialized_entry_id)
                        if item.materialized_entry_id is not None
                        else None
                    ),
                }
                for item in memory
            ],
            "skill_proposals": [
                {
                    "proposal_id": item.proposal_id,
                    "skill_name": item.skill_name,
                    "content_hash": item.content_hash,
                    "proposed_by_agent": item.proposed_by_agent,
                    "state": item.state.value,
                    "reviewed_by": item.reviewed_by,
                    "review_reason": item.review_reason,
                }
                for item in skills
            ],
        }


def _durable_metrics(reviews: tuple[Any, ...]) -> dict[str, int]:
    states = Counter(item.state.value for item in reviews)
    return {
        "eligible": sum(count for state, count in states.items() if state != "ineligible"),
        "ineligible": states["ineligible"],
        "abstained": states["abstained"],
        "duplicates": states["duplicate"],
        "routed": states["routed"],
        "failed": states["failed"],
    }


__all__ = ["PostTurnReviewPanel"]
