"""Knowledge context lifecycle and failure-state coverage."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from fdai.core.learning import (
    InMemoryPostTurnReviewLedger,
    PostTurnProposalKind,
    PostTurnReviewRecord,
    PostTurnReviewState,
)
from fdai.core.operator_memory import (
    InMemoryOperatorMemoryProposalStore,
    InMemoryOperatorMemoryStore,
    MemoryCategory,
    MemorySource,
    OperatorMemoryEntry,
    OperatorMemoryProposal,
    OperatorMemoryProposalState,
    ScopeKind,
)
from fdai.core.skills import (
    InMemorySkillProposalStore,
    RuntimeSkillDisclosure,
    SkillProposal,
    SkillProposalState,
)
from fdai.core.skills.source_registry import (
    SkillSource,
    SkillSourceKind,
    SkillSourceRefreshPolicy,
    SkillSourceTrustTier,
)
from fdai.core.supply_chain.skill_quarantine import SkillSourceRefreshState
from fdai.delivery.operator_api.production.knowledge_context import (
    build_production_knowledge_context,
)
from fdai.delivery.operator_api.routes.chat_knowledge_context import KnowledgeContextChatTools
from fdai.delivery.persistence import (
    PostgresSkillSourceRefreshStateStore,
    PostgresSkillSourceStore,
)
from fdai.shared.providers.testing.user_context import InMemoryUserMemoryStore
from fdai.shared.providers.user_context import UserMemoryCategory, UserMemoryFact
from tests.delivery.operator_api.test_chat_knowledge_context import (
    _NOW,
    _TURN_ID,
    _context,
    _disclosure,
    _RefreshStates,
    _Sources,
)


@pytest.mark.parametrize(
    ("disclosure", "expected_reason"),
    [
        (None, "trusted_skill_catalog_unavailable"),
        (_disclosure(enabled=False), "no_applicable_reviewed_runbook"),
    ],
)
async def test_unavailable_or_disabled_runbook_never_becomes_recommendation(
    disclosure: RuntimeSkillDisclosure | None,
    expected_reason: str,
) -> None:
    result = await KnowledgeContextChatTools(skill_disclosure=disclosure).resolve_with_context(
        "runbook",
        principal_id="reader",
        context=_context(),
        intent=SimpleNamespace(value="runbook"),
    )

    assert result["result"]["status"] in {"empty", "unavailable"}
    assert result["result"]["reason"] == expected_reason
    assert "recommend" not in result["result"]["data"]


async def test_source_future_observation_and_refresh_error_are_not_fresh() -> None:
    future = _source("future-runbooks")
    failed = _source("failed-runbooks")
    resolver = KnowledgeContextChatTools(
        skill_sources=_Sources(future, failed),
        skill_refresh_states=_RefreshStates(
            {
                future.source_id: SkillSourceRefreshState(
                    source_id=future.source_id,
                    last_refresh_at=_NOW + timedelta(minutes=1),
                ),
                failed.source_id: SkillSourceRefreshState(
                    source_id=failed.source_id,
                    last_refresh_at=_NOW - timedelta(minutes=10),
                    error_count=2,
                    retry_at=_NOW + timedelta(minutes=5),
                    last_error_kind="network_error",
                ),
            }
        ),
        clock=lambda: _NOW,
    )

    result = await resolver.resolve_with_context(
        "sources",
        principal_id="reader",
        context=_context(),
        intent=SimpleNamespace(value="knowledge_sources"),
    )

    by_id = {item["source_id"]: item for item in result["result"]["data"]["sources"]}
    assert by_id[future.source_id]["freshness"] == "invalid_future_observation"
    assert by_id[future.source_id]["fresh"] is False
    assert by_id[failed.source_id]["freshness"] == "error"
    assert by_id[failed.source_id]["connected"] is False
    assert by_id[failed.source_id]["error_count"] == 2
    assert by_id[failed.source_id]["retry_at"] == (_NOW + timedelta(minutes=5)).isoformat()


async def test_expired_memory_is_not_disclosed() -> None:
    store = InMemoryUserMemoryStore()
    await store.create(
        UserMemoryFact(
            memory_id="memory-expired",
            principal_id="reader",
            category=UserMemoryCategory.CONTEXT,
            body="Expired recovery guidance.",
            source_turn_id=_TURN_ID,
            consented_at=_NOW - timedelta(hours=2),
            created_at=_NOW - timedelta(hours=2),
            expires_at=_NOW - timedelta(hours=1),
        )
    )

    result = await KnowledgeContextChatTools(
        user_memories=store,
        clock=lambda: _NOW,
    ).resolve_with_context(
        "memory",
        principal_id="reader",
        context=_context(),
        intent=SimpleNamespace(value="memory"),
    )

    assert result["result"]["status"] == "empty"
    assert "Expired recovery guidance" not in repr(result)


async def test_pending_review_is_not_reported_as_learned() -> None:
    reviews = InMemoryPostTurnReviewLedger()
    review_id = _review_id()
    await reviews.start(
        PostTurnReviewRecord(
            review_id=review_id,
            principal_scope=_principal_scope(),
            state=PostTurnReviewState.PENDING,
            reasons=("eligible_repeated_procedure",),
            created_at=_NOW,
            updated_at=_NOW,
        )
    )

    result = await KnowledgeContextChatTools(post_turn_reviews=reviews).resolve_with_context(
        "learning",
        principal_id="reader",
        context=_context(),
        intent=SimpleNamespace(value="learning"),
    )

    assert result["result"]["status"] == "empty"
    assert result["result"]["reason"] == "review_pending"
    assert result["result"]["data"]["reusable"] is False


async def test_materialized_enabled_skill_is_reusable_learning() -> None:
    reviews = InMemoryPostTurnReviewLedger()
    proposals = InMemorySkillProposalStore()
    proposal_id = "skill-proposal:cache-recovery"
    pending = PostTurnReviewRecord(
        review_id=_review_id(),
        principal_scope=_principal_scope(),
        state=PostTurnReviewState.PENDING,
        reasons=("eligible_repeated_procedure",),
        created_at=_NOW,
        updated_at=_NOW,
    )
    await reviews.start(pending)
    await reviews.finish(
        pending.review_id,
        state=PostTurnReviewState.ROUTED,
        reasons=pending.reasons,
        updated_at=_NOW,
        proposal_kind=PostTurnProposalKind.SKILL_DRAFT,
        proposal_ref=proposal_id,
    )
    await proposals.create(
        SkillProposal(
            proposal_id=proposal_id,
            skill_name="cache-redis-recovery",
            content_hash="c" * 64,
            markdown=b"reviewed skill",
            proposed_by_agent="Norns",
            created_at=_NOW,
            state=SkillProposalState.MATERIALIZED,
            reviewed_by="reviewer-1",
            review_reason="procedure verified",
            reviewed_at=_NOW,
        )
    )

    result = await KnowledgeContextChatTools(
        skill_disclosure=_disclosure(),
        post_turn_reviews=reviews,
        skill_proposals=proposals,
    ).resolve_with_context(
        "learning",
        principal_id="reader",
        context=_context(),
        intent=SimpleNamespace(value="learning"),
    )

    assert result["result"]["status"] == "matched"
    assert result["result"]["data"]["kind"] == "runtime_skill"
    assert result["result"]["data"]["retained"] is True
    assert result["result"]["data"]["reusable"] is True
    assert any(
        ref.startswith("trusted-skill-lesson:sha256:") for ref in result["result"]["evidence_refs"]
    )


async def test_materialized_memory_requires_store_and_exact_source_identity() -> None:
    reviews = InMemoryPostTurnReviewLedger()
    proposals = InMemoryOperatorMemoryProposalStore()
    memories = InMemoryOperatorMemoryStore(now_fn=lambda: _NOW)
    proposal_id = "operator-memory-proposal:identity"
    entry_id = UUID("00000000-0000-0000-0000-000000000004")
    pending = PostTurnReviewRecord(
        review_id=_review_id(),
        principal_scope=_principal_scope(),
        state=PostTurnReviewState.PENDING,
        reasons=("eligible_repeated_procedure",),
        created_at=_NOW,
        updated_at=_NOW,
    )
    await reviews.start(pending)
    await reviews.finish(
        pending.review_id,
        state=PostTurnReviewState.ROUTED,
        reasons=pending.reasons,
        updated_at=_NOW,
        proposal_kind=PostTurnProposalKind.OPERATOR_MEMORY,
        proposal_ref=proposal_id,
    )

    missing_store = await KnowledgeContextChatTools(post_turn_reviews=reviews).resolve_with_context(
        "learning",
        principal_id="reader",
        context=_context(),
        intent=SimpleNamespace(value="learning"),
    )
    assert missing_store["result"]["status"] == "unavailable"
    assert missing_store["result"]["reason"] == "memory_proposal_store_unavailable"

    await proposals.create(
        OperatorMemoryProposal(
            proposal_id=proposal_id,
            content_hash="d" * 64,
            scope_kind=ScopeKind.RESOURCE,
            scope_ref="resource/cache-app",
            category=MemoryCategory.RUNBOOK_HINT,
            body="Verify cache health before restart.",
            evidence_refs=("health:event",),
            proposed_by_agent="Norns",
            created_at=_NOW,
            state=OperatorMemoryProposalState.MATERIALIZED,
            reviewed_by="reviewer-1",
            review_reason="evidence confirmed",
            reviewed_at=_NOW,
            materialized_entry_id=entry_id,
        )
    )
    await memories.append(
        OperatorMemoryEntry(
            id=entry_id,
            scope_kind=ScopeKind.RESOURCE,
            scope_ref="resource/cache-app",
            category=MemoryCategory.RUNBOOK_HINT,
            body="Verify cache health before restart.",
            source_event=MemorySource.POST_TURN_REVIEW,
            source_ref="operator-memory-proposal:wrong",
            author="Norns",
            approved_by="reviewer-1",
            created_at=_NOW,
        )
    )
    mismatch = await KnowledgeContextChatTools(
        post_turn_reviews=reviews,
        memory_proposals=proposals,
        operator_memories=memories,
    ).resolve_with_context(
        "learning",
        principal_id="reader",
        context=_context(),
        intent=SimpleNamespace(value="learning"),
    )

    assert mismatch["result"]["status"] == "empty"
    assert mismatch["result"]["reason"] == "materialized_lesson_inactive"
    assert mismatch["result"]["data"]["reusable"] is False


def test_persisted_builder_supplies_source_read_stores_without_lifecycle() -> None:
    provider = build_production_knowledge_context(
        dsn="unused",
        statement_timeout_ms=1_000,
        connect_timeout_s=1,
        skill_disclosure=_disclosure(),
        user_memories=InMemoryUserMemoryStore(),
    )

    assert isinstance(provider.skill_sources, PostgresSkillSourceStore)
    assert isinstance(provider.skill_refresh_states, PostgresSkillSourceRefreshStateStore)


def _source(source_id: str) -> SkillSource:
    return SkillSource(
        source_id=source_id,
        kind=SkillSourceKind.GITHUB_REPOSITORY,
        location=f"example/{source_id}",
        trust_tier=SkillSourceTrustTier.ORGANIZATION_APPROVED,
        owner="platform-team",
        allowed_path="skills",
        authentication_audience_ref="secret/source-reader",
        refresh_policy=SkillSourceRefreshPolicy.SCHEDULED,
        refresh_interval_seconds=3_600,
        enabled=True,
    )


def _review_id() -> str:
    return f"review-{hashlib.sha256(_TURN_ID.encode()).hexdigest()[:32]}"


def _principal_scope() -> str:
    return f"principal-{hashlib.sha256(b'reader').hexdigest()[:32]}"
