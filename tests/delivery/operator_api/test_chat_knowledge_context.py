"""Read-only knowledge context is exact, reviewed, and provenance-bearing."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

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
    RuntimeSkill,
    RuntimeSkillDisclosure,
    SkillCatalog,
    skill_body_digest,
)
from fdai.core.skills.source_registry import (
    SkillSource,
    SkillSourceKind,
    SkillSourceRefreshPolicy,
    SkillSourceTrustTier,
)
from fdai.core.supply_chain.skill_quarantine import SkillSourceRefreshState
from fdai.delivery.operator_api.application.conversation.capabilities.conversation_context import (
    ConversationContextChatTools,
)
from fdai.delivery.operator_api.application.conversation.capabilities.knowledge_context import (
    KnowledgeContextChatTools,
    render_knowledge_context_answer,
)
from fdai.delivery.operator_api.routes.chat import make_chat_route, make_chat_stream_route
from fdai.delivery.operator_api.routes.chat_history import replay_metadata
from fdai.shared.providers.testing.user_context import (
    InMemoryConversationHistoryStore,
    InMemoryUserMemoryStore,
)
from fdai.shared.providers.user_context import (
    ConversationRecord,
    ConversationTurnRecord,
    ConversationTurnRole,
    UserMemoryCategory,
    UserMemoryFact,
)

_NOW = datetime(2026, 7, 22, 6, 0, tzinfo=UTC)
_TURN_ID = "turn:seed:assistant"


class _NoNarrator:
    async def answer(self, **kwargs: object) -> dict[str, str]:
        del kwargs
        raise AssertionError("knowledge evidence fast path must not call the narrator")


async def _allow(_request: Request) -> str:
    return "reader"


class _Verifier:
    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        del skill, raw_markdown
        return True


class _Sources:
    def __init__(self, *sources: SkillSource) -> None:
        self._sources = sources

    async def list(self, *, enabled_only: bool = False) -> tuple[SkillSource, ...]:
        return tuple(source for source in self._sources if not enabled_only or source.enabled)


class _RefreshStates:
    def __init__(self, states: dict[str, SkillSourceRefreshState]) -> None:
        self._states = states

    async def get(self, source_id: str) -> SkillSourceRefreshState | None:
        return self._states.get(source_id)


def _disclosure(*, ambiguous: bool = False, enabled: bool = True) -> RuntimeSkillDisclosure:
    verifier = _Verifier()
    catalog = SkillCatalog()
    names = (
        ("cache-redis-recovery", "cache-redis-secondary")
        if ambiguous
        else ("cache-redis-recovery",)
    )
    for name in names:
        body = f"Restart only after the cache redis health gate passes for {name}."
        raw = f"""---
name: {name}
version: 1.0.0
description: Reviewed cache redis recovery runbook.
source: publisher.example
body_sha256: "{skill_body_digest(body)}"
required_tools: [query_inventory]
allowed_agents: [Bragi]
---
{body}
""".encode()
        catalog = catalog.install(raw, verifier=verifier)
        if enabled:
            catalog = catalog.enable(
                name,
                available_tools=frozenset({"query_inventory"}),
                known_agents=frozenset({"Bragi"}),
            )
    return RuntimeSkillDisclosure(
        catalog=catalog,
        verifier=verifier,
        agent="Bragi",
        available_tools=frozenset({"query_inventory"}),
    )


def _context() -> dict[str, object]:
    return {
        "principal_id": "reader",
        "conversation_id": "knowledge-context",
        "turn_id": _TURN_ID,
        "status": "verified",
        "authority": "server_subscription_health",
        "answer": "The cache is degraded.",
        "evidence_refs": ["health:event"],
        "resource_context": {
            "name": "cache-app",
            "resource_type": "cache.redis",
            "evidence_ref": "inventory:cache-app",
        },
    }


async def test_unique_trusted_runbook_is_loaded_with_citations() -> None:
    result = await KnowledgeContextChatTools(skill_disclosure=_disclosure()).resolve_with_context(
        "runbook",
        principal_id="reader",
        context=_context(),
        intent=SimpleNamespace(value="runbook"),
    )

    assert result["result"]["status"] == "matched"
    assert result["result"]["data"]["name"] == "cache-redis-recovery"
    assert "health gate passes" in result["result"]["data"]["body"]
    assert len(result["result"]["evidence_refs"]) == 3
    assert render_knowledge_context_answer(result, locale="en").startswith(
        "Applicable runbook: cache-redis-recovery"
    )


async def test_prior_context_principal_mismatch_fails_closed() -> None:
    context = _context()
    context["principal_id"] = "other-reader"

    result = await KnowledgeContextChatTools(skill_disclosure=_disclosure()).resolve_with_context(
        "runbook",
        principal_id="reader",
        context=context,
        intent=SimpleNamespace(value="runbook"),
    )

    assert result["result"]["status"] == "unavailable"
    assert result["result"]["reason"] == "prior_context_principal_mismatch"


async def test_ambiguous_runbooks_do_not_generate_recommendation() -> None:
    result = await KnowledgeContextChatTools(
        skill_disclosure=_disclosure(ambiguous=True)
    ).resolve_with_context(
        "runbook",
        principal_id="reader",
        context=_context(),
        intent=SimpleNamespace(value="runbook"),
    )

    assert result["result"]["status"] == "empty"
    assert result["result"]["reason"] == "applicable_runbook_ambiguous"
    assert "No recommendation was generated" in render_knowledge_context_answer(result, locale="en")


async def test_source_freshness_distinguishes_current_from_unobserved() -> None:
    current = SkillSource(
        source_id="approved-runbooks",
        kind=SkillSourceKind.GITHUB_REPOSITORY,
        location="example/runbooks",
        trust_tier=SkillSourceTrustTier.ORGANIZATION_APPROVED,
        owner="platform-team",
        allowed_path="skills",
        authentication_audience_ref="secret/source-reader",
        refresh_policy=SkillSourceRefreshPolicy.SCHEDULED,
        refresh_interval_seconds=3_600,
        enabled=True,
    )
    unknown = SkillSource(
        source_id="manual-runbooks",
        kind=SkillSourceKind.GITHUB_REPOSITORY,
        location="example/manual-runbooks",
        trust_tier=SkillSourceTrustTier.ORGANIZATION_APPROVED,
        owner="operations-team",
        allowed_path="runbooks",
        authentication_audience_ref="secret/manual-reader",
        refresh_policy=SkillSourceRefreshPolicy.MANUAL,
        refresh_interval_seconds=3_600,
        enabled=True,
    )
    resolver = KnowledgeContextChatTools(
        skill_sources=_Sources(current, unknown),
        skill_refresh_states=_RefreshStates(
            {
                current.source_id: SkillSourceRefreshState(
                    source_id=current.source_id,
                    last_refresh_at=_NOW - timedelta(minutes=10),
                    next_refresh_at=_NOW + timedelta(minutes=50),
                    last_revision="revision-1",
                )
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

    sources = result["result"]["data"]["sources"]
    assert sources[0]["authorized"] is True
    assert sources[0]["enabled"] is True
    assert sources[0]["connected"] is True
    assert sources[0]["fresh"] is True
    assert sources[1]["connected"] is False
    assert sources[1]["fresh"] is None
    assert sources[1]["freshness"] == "unknown"
    assert len(result["result"]["evidence_refs"]) == 4


async def test_source_freshness_uses_policy_deadline_and_reports_truncation() -> None:
    sources = tuple(
        SkillSource(
            source_id=f"source-{index:03d}",
            kind=SkillSourceKind.GITHUB_REPOSITORY,
            location=f"example/runbooks-{index:03d}",
            trust_tier=SkillSourceTrustTier.ORGANIZATION_APPROVED,
            owner="platform-team",
            allowed_path="skills",
            authentication_audience_ref="secret/source-reader",
            refresh_policy=SkillSourceRefreshPolicy.SCHEDULED,
            refresh_interval_seconds=3_600,
            enabled=True,
        )
        for index in range(51)
    )
    refresh = SkillSourceRefreshState(
        source_id=sources[0].source_id,
        last_refresh_at=_NOW - timedelta(hours=2),
        next_refresh_at=_NOW + timedelta(days=365),
        last_revision="revision-old",
    )
    resolver = KnowledgeContextChatTools(
        skill_sources=_Sources(*sources),
        skill_refresh_states=_RefreshStates({sources[0].source_id: refresh}),
        clock=lambda: _NOW,
    )

    result = await resolver.resolve_with_context(
        "sources",
        principal_id="reader",
        context=_context(),
        intent=SimpleNamespace(value="knowledge_sources"),
    )

    data = result["result"]["data"]
    assert data["sources"][0]["freshness"] == "stale"
    assert data["sources"][0]["fresh"] is False
    assert data["total_enabled"] == 51
    assert data["returned"] == 50
    assert data["truncated"] is True
    assert "Display limit: 50/51 sources" in render_knowledge_context_answer(
        result,
        locale="en",
    )


async def test_memory_requires_explicit_consent_and_remains_principal_scoped() -> None:
    store = InMemoryUserMemoryStore()
    resolver = KnowledgeContextChatTools(user_memories=store, clock=lambda: _NOW)

    empty = await resolver.resolve_with_context(
        "memory",
        principal_id="reader",
        context=_context(),
        intent=SimpleNamespace(value="memory"),
    )
    assert empty["result"]["status"] == "empty"
    assert empty["result"]["data"]["persisted"] is False
    assert empty["result"]["data"]["would_store"]["write_performed_by_chat"] is False

    await store.create(
        UserMemoryFact(
            memory_id="memory-1",
            principal_id="reader",
            category=UserMemoryCategory.CONTEXT,
            body="Use the verified cache recovery sequence.",
            source_turn_id=_TURN_ID,
            consented_at=_NOW,
            created_at=_NOW,
        )
    )
    matched = await resolver.resolve_with_context(
        "memory",
        principal_id="reader",
        context=_context(),
        intent=SimpleNamespace(value="memory"),
    )
    other = await resolver.resolve_with_context(
        "memory",
        principal_id="other-reader",
        context=_context(),
        intent=SimpleNamespace(value="memory"),
    )
    other_context = _context()
    other_context["principal_id"] = "other-reader"
    other_empty = await resolver.resolve_with_context(
        "memory",
        principal_id="other-reader",
        context=other_context,
        intent=SimpleNamespace(value="memory"),
    )

    assert matched["result"]["status"] == "matched"
    assert matched["result"]["data"]["memories"][0]["visibility"] == "principal_only"
    assert other["result"]["status"] == "unavailable"
    assert other["result"]["reason"] == "prior_context_principal_mismatch"
    assert other_empty["result"]["status"] == "empty"


async def test_only_materialized_review_is_reported_as_reusable_learning() -> None:
    reviews = InMemoryPostTurnReviewLedger()
    proposals = InMemoryOperatorMemoryProposalStore()
    operator_memories = InMemoryOperatorMemoryStore(now_fn=lambda: _NOW)
    review_id = f"review-{hashlib.sha256(_TURN_ID.encode()).hexdigest()[:32]}"
    principal_scope = f"principal-{hashlib.sha256(b'reader').hexdigest()[:32]}"
    proposal_id = "operator-memory-proposal:retained"
    pending = PostTurnReviewRecord(
        review_id=review_id,
        principal_scope=principal_scope,
        state=PostTurnReviewState.PENDING,
        reasons=("eligible_repeated_procedure",),
        created_at=_NOW,
        updated_at=_NOW,
    )
    await reviews.start(pending)
    await reviews.finish(
        review_id,
        state=PostTurnReviewState.ROUTED,
        reasons=pending.reasons,
        updated_at=_NOW,
        proposal_kind=PostTurnProposalKind.OPERATOR_MEMORY,
        proposal_ref=proposal_id,
    )
    await proposals.create(
        OperatorMemoryProposal(
            proposal_id=proposal_id,
            content_hash="a" * 64,
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
            materialized_entry_id=UUID("00000000-0000-0000-0000-000000000001"),
        )
    )
    await operator_memories.append(
        OperatorMemoryEntry(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            scope_kind=ScopeKind.RESOURCE,
            scope_ref="resource/cache-app",
            category=MemoryCategory.RUNBOOK_HINT,
            body="Verify cache health before restart.",
            source_event=MemorySource.POST_TURN_REVIEW,
            source_ref=proposal_id,
            author="Norns",
            approved_by="reviewer-1",
            created_at=_NOW,
        )
    )
    resolver = KnowledgeContextChatTools(
        post_turn_reviews=reviews,
        memory_proposals=proposals,
        operator_memories=operator_memories,
        clock=lambda: _NOW,
    )

    result = await resolver.resolve_with_context(
        "learning",
        principal_id="reader",
        context=_context(),
        intent=SimpleNamespace(value="learning"),
    )

    assert result["result"]["status"] == "matched"
    assert result["result"]["data"]["reviewed_by"] == "reviewer-1"
    assert result["result"]["data"]["retained"] is True
    assert result["result"]["data"]["reusable"] is True
    assert "재사용 조건" in render_knowledge_context_answer(result, locale="ko")

    replacement = await operator_memories.append(
        OperatorMemoryEntry(
            id=UUID("00000000-0000-0000-0000-000000000003"),
            scope_kind=ScopeKind.RESOURCE,
            scope_ref="resource/cache-app",
            category=MemoryCategory.RUNBOOK_HINT,
            body="Use the revised cache recovery sequence.",
            source_event=MemorySource.POST_TURN_REVIEW,
            source_ref="operator-memory-proposal:replacement",
            author="Norns",
            approved_by="reviewer-2",
            created_at=_NOW,
        )
    )
    await operator_memories.supersede(
        entry_id=UUID("00000000-0000-0000-0000-000000000001"),
        superseded_by=replacement.id,
    )

    stale = await resolver.resolve_with_context(
        "learning",
        principal_id="reader",
        context=_context(),
        intent=SimpleNamespace(value="learning"),
    )

    assert stale["result"]["status"] == "empty"
    assert stale["result"]["reason"] == "materialized_lesson_inactive"
    assert stale["result"]["data"]["reusable"] is False


async def _seed_history(store: InMemoryConversationHistoryStore, session_id: str) -> None:
    await store.create_conversation(
        ConversationRecord(
            conversation_id=session_id,
            principal_id="reader",
            channel_id="web",
            started_at=_NOW,
            last_active=_NOW,
        )
    )
    payload = {
        "answer": "The cache is degraded.",
        "model": "deterministic",
        "verification": {
            "status": "verified",
            "authority": "server_subscription_health",
            "checks_completed": 1,
            "checks_total": 1,
            "evidence_refs": ["health:event"],
            "reason_code": "subscription_health_grounded",
        },
        "resource_context": _context()["resource_context"],
    }
    await store.append_turn(
        ConversationTurnRecord(
            turn_id=_TURN_ID,
            conversation_id=session_id,
            principal_id="reader",
            turn_index=0,
            role=ConversationTurnRole.ASSISTANT,
            content="The cache is degraded.",
            recorded_at=_NOW,
            idempotency_key=f"seed:{session_id}",
            metadata=replay_metadata(model="deterministic", payload=payload),
        ),
        allocate_index=True,
    )


async def _full_provider() -> KnowledgeContextChatTools:
    source = SkillSource(
        source_id="approved-runbooks",
        kind=SkillSourceKind.GITHUB_REPOSITORY,
        location="example/runbooks",
        trust_tier=SkillSourceTrustTier.ORGANIZATION_APPROVED,
        owner="platform-team",
        allowed_path="skills",
        authentication_audience_ref="secret/source-reader",
        refresh_policy=SkillSourceRefreshPolicy.SCHEDULED,
        refresh_interval_seconds=3_600,
        enabled=True,
    )
    memories = InMemoryUserMemoryStore()
    await memories.create(
        UserMemoryFact(
            memory_id="memory-route-1",
            principal_id="reader",
            category=UserMemoryCategory.CONTEXT,
            body="Use the verified cache recovery sequence.",
            source_turn_id=_TURN_ID,
            consented_at=_NOW,
            created_at=_NOW,
        )
    )
    reviews = InMemoryPostTurnReviewLedger()
    proposals = InMemoryOperatorMemoryProposalStore()
    operator_memories = InMemoryOperatorMemoryStore(now_fn=lambda: _NOW)
    review_id = f"review-{hashlib.sha256(_TURN_ID.encode()).hexdigest()[:32]}"
    principal_scope = f"principal-{hashlib.sha256(b'reader').hexdigest()[:32]}"
    proposal_id = "operator-memory-proposal:route-retained"
    await reviews.start(
        PostTurnReviewRecord(
            review_id=review_id,
            principal_scope=principal_scope,
            state=PostTurnReviewState.PENDING,
            reasons=("eligible_repeated_procedure",),
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    await reviews.finish(
        review_id,
        state=PostTurnReviewState.ROUTED,
        reasons=("eligible_repeated_procedure",),
        updated_at=_NOW,
        proposal_kind=PostTurnProposalKind.OPERATOR_MEMORY,
        proposal_ref=proposal_id,
    )
    await proposals.create(
        OperatorMemoryProposal(
            proposal_id=proposal_id,
            content_hash="b" * 64,
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
            materialized_entry_id=UUID("00000000-0000-0000-0000-000000000002"),
        )
    )
    await operator_memories.append(
        OperatorMemoryEntry(
            id=UUID("00000000-0000-0000-0000-000000000002"),
            scope_kind=ScopeKind.RESOURCE,
            scope_ref="resource/cache-app",
            category=MemoryCategory.RUNBOOK_HINT,
            body="Verify cache health before restart.",
            source_event=MemorySource.POST_TURN_REVIEW,
            source_ref=proposal_id,
            author="Norns",
            approved_by="reviewer-1",
            created_at=_NOW,
        )
    )
    return KnowledgeContextChatTools(
        skill_disclosure=_disclosure(),
        skill_sources=_Sources(source),
        skill_refresh_states=_RefreshStates(
            {
                source.source_id: SkillSourceRefreshState(
                    source_id=source.source_id,
                    last_refresh_at=_NOW - timedelta(minutes=10),
                    next_refresh_at=_NOW + timedelta(minutes=50),
                    last_revision="revision-1",
                )
            }
        ),
        user_memories=memories,
        post_turn_reviews=reviews,
        memory_proposals=proposals,
        operator_memories=operator_memories,
        clock=lambda: _NOW,
    )


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    ("prompt", "expected", "reason_code"),
    [
        (
            "이 문제와 관련된 런북 내용을 출처와 함께 알려줘.",
            "적용 런북",
            "knowledge_runbook_grounded",
        ),
        (
            "What does the applicable runbook recommend, with source citations?",
            "Applicable runbook",
            "knowledge_runbook_grounded",
        ),
        (
            "연결된 지식 원본과 마지막 갱신 시점을 보여줘.",
            "마지막 갱신",
            "knowledge_knowledge_sources_grounded",
        ),
        (
            "Which knowledge sources are connected, authorized, and fresh?",
            "Freshness",
            "knowledge_knowledge_sources_grounded",
        ),
        (
            "이 해결 방법을 기억할 때 무엇을 저장하고 누가 볼 수 있어?",
            "principal 전용 memory",
            "knowledge_memory_grounded",
        ),
        (
            "What would be stored as durable memory, with consent and provenance?",
            "Persisted principal-only memory",
            "knowledge_memory_grounded",
        ),
        (
            "이 인시던트에서 학습한 내용과 재사용 조건은 뭐야?",
            "재사용 조건",
            "knowledge_learning_grounded",
        ),
        (
            "What reusable lesson was learned, reviewed, and retained?",
            "Reuse conditions",
            "knowledge_learning_grounded",
        ),
    ],
)
def test_knowledge_context_json_sse_bilingual_parity(
    stream: bool,
    prompt: str,
    expected: str,
    reason_code: str,
) -> None:
    store = InMemoryConversationHistoryStore()
    transport = "stream" if stream else "json"
    prompt_digest = hashlib.sha256(prompt.encode()).hexdigest()[:8]
    session_id = f"knowledge-{transport}-{prompt_digest}"
    asyncio.run(_seed_history(store, session_id))
    resolver = ConversationContextChatTools(knowledge_context=asyncio.run(_full_provider()))
    route = (
        make_chat_stream_route(
            backend=_NoNarrator(),
            authorize=_allow,
            tool_resolver=resolver,
            conversation_history_store=store,
        )
        if stream
        else make_chat_route(
            backend=_NoNarrator(),
            authorize=_allow,
            tool_resolver=resolver,
            conversation_history_store=store,
        )
    )

    with TestClient(Starlette(routes=[route])) as client:
        response = client.post(
            "/chat/stream" if stream else "/chat",
            json={"prompt": prompt, "session_id": session_id},
        )

    assert response.status_code == 200
    assert expected in response.text
    assert "server_knowledge_context" in response.text
    assert reason_code in response.text
    if not stream:
        assert json.loads(response.text)["verification"]["status"] in {"verified", "corrected"}
