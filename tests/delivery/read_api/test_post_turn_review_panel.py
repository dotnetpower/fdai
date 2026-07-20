from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.learning import (
    InMemoryPostTurnReviewLedger,
    PostTurnProposalKind,
    PostTurnReviewMetrics,
    PostTurnReviewState,
)
from fdai.core.learning.ledger import pending_record
from fdai.core.learning.models import EligibilityReason
from fdai.core.operator_memory import (
    InMemoryOperatorMemoryProposalStore,
    MemoryCategory,
    OperatorMemoryProposal,
    OperatorMemoryProposalState,
    ScopeKind,
)
from fdai.core.skills import (
    InMemorySkillProposalStore,
    SkillProposal,
    SkillProposalState,
)
from fdai.delivery.read_api.routes.post_turn_review_panel import PostTurnReviewPanel

_NOW = datetime(2026, 7, 20, tzinfo=UTC)


async def test_panel_projects_terminal_review_state_and_metrics() -> None:
    ledger = InMemoryPostTurnReviewLedger()
    await ledger.start(
        pending_record(
            review_id="review-1",
            principal_scope="principal-hash-1",
            reasons=(EligibilityReason.ELIGIBLE_CORRECTION,),
            at=_NOW,
        )
    )
    await ledger.finish(
        "review-1",
        state=PostTurnReviewState.ABSTAINED,
        reasons=("model_disagreement",),
        updated_at=_NOW,
    )
    metrics = PostTurnReviewMetrics()
    metrics.increment("abstained")
    panel = PostTurnReviewPanel(
        reviews=ledger,
        memory_proposals=InMemoryOperatorMemoryProposalStore(),
        skill_proposals=InMemorySkillProposalStore(),
        metrics=metrics,
        source="test",
        durable=False,
    )

    result = await panel.render(params={})

    assert result["reviews"][0]["state"] == "abstained"
    assert result["metrics"]["abstained"] == 1


async def test_durable_panel_aggregates_all_rows_beyond_display_limit() -> None:
    ledger = InMemoryPostTurnReviewLedger()
    for review_id, state, proposal_kind in (
        ("review-1", PostTurnReviewState.INELIGIBLE, None),
        ("review-2", PostTurnReviewState.ROUTED, PostTurnProposalKind.OPERATOR_MEMORY),
    ):
        await ledger.start(
            pending_record(
                review_id=review_id,
                principal_scope="principal-hash-1",
                reasons=(EligibilityReason.ELIGIBLE_CORRECTION,),
                at=_NOW,
            )
        )
        await ledger.finish(
            review_id,
            state=state,
            reasons=("terminal",),
            updated_at=_NOW,
            proposal_kind=proposal_kind,
            proposal_ref="proposal-1" if state is PostTurnReviewState.ROUTED else None,
        )
    memory = InMemoryOperatorMemoryProposalStore()
    await memory.create(
        OperatorMemoryProposal(
            proposal_id="memory-1",
            content_hash="a" * 64,
            scope_kind=ScopeKind.RESOURCE,
            scope_ref="resource-hash-1",
            category=MemoryCategory.RUNBOOK_HINT,
            body="Use bounded evidence.",
            evidence_refs=("audit:1",),
            proposed_by_agent="Norns",
            created_at=_NOW,
            state=OperatorMemoryProposalState.APPROVED,
            reviewed_by="reviewer-1",
            review_reason="Evidence is sufficient.",
            reviewed_at=_NOW,
        )
    )
    skills = InMemorySkillProposalStore()
    await skills.create(
        SkillProposal(
            proposal_id="skill-1",
            skill_name="bounded-review",
            content_hash="b" * 64,
            markdown=b"review",
            proposed_by_agent="Norns",
            created_at=_NOW,
            state=SkillProposalState.REJECTED,
            reviewed_by="reviewer-2",
            review_reason="Not reusable.",
            reviewed_at=_NOW,
        )
    )
    panel = PostTurnReviewPanel(
        reviews=ledger,
        memory_proposals=memory,
        skill_proposals=skills,
        metrics=PostTurnReviewMetrics(),
        source="postgres",
        durable=True,
    )

    result = await panel.render(params={"limit": "1"})

    assert len(result["reviews"]) == 1
    assert result["metrics"] == {
        "eligible": 1,
        "ineligible": 1,
        "abstained": 0,
        "duplicates": 0,
        "routed": 1,
        "failed": 0,
    }
    assert result["proposal_types"] == {"operator_memory": 1}
    assert result["proposal_states"] == {
        "operator_memory": {"approved": 1},
        "skill": {"rejected": 1},
    }
    assert result["operator_acceptance_rate"] == 0.5
