from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

from fdai.core.learning import (
    NoImprovement,
    OperatorMemoryCandidate,
    PostTurnProposal,
    PostTurnReviewInput,
    PostTurnReviewState,
)
from fdai.core.operator_memory import (
    InMemoryOperatorMemoryStore,
    MemoryCategory,
    ScopeKind,
)
from fdai.delivery.azure.llm.request_target import COGNITIVE_SERVICES_SCOPE
from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    ResolvedCapability,
    ResolvedModels,
)
from fdai.runtime.post_turn_review import (
    build_azure_post_turn_models,
    build_post_turn_review_runtime,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

_NOW = datetime(2026, 7, 20, 2, tzinfo=UTC)


class _Model:
    def __init__(
        self,
        *,
        identity: str,
        family: str,
        result: PostTurnProposal | NoImprovement,
    ) -> None:
        self._identity = identity
        self._family = family
        self._result = result

    @property
    def model_identity(self) -> str:
        return self._identity

    @property
    def model_family(self) -> str:
        return self._family

    async def propose(
        self,
        review_input: PostTurnReviewInput,  # noqa: ARG002
    ) -> PostTurnProposal | NoImprovement:
        return self._result


def _review_input() -> PostTurnReviewInput:
    return PostTurnReviewInput(
        review_id="review-runtime-1",
        principal_scope="principal-hash-1",
        operator_turn_id="operator-turn-1",
        assistant_turn_id="assistant-turn-1",
        completed_at=_NOW,
        operator_body="Inspect the bounded incident evidence.",
        assistant_body="The bounded inspection completed.",
        explicit_corrections=("Use the resource-scoped query next time.",),
        evidence_refs=("audit:1",),
        memory_scope_kind=ScopeKind.RESOURCE,
        memory_scope_ref="resource-hash-1",
    )


async def test_runtime_routes_consensus_to_durable_owner_workshop() -> None:
    state_store = InMemoryStateStore()
    proposal = OperatorMemoryCandidate(
        scope_kind=ScopeKind.RESOURCE,
        scope_ref="resource-hash-1",
        category=MemoryCategory.RUNBOOK_HINT,
        body="Use the resource-scoped query before escalation.",
        evidence_refs=("audit:1",),
        confidence=0.9,
    )
    runtime = build_post_turn_review_runtime(
        state_store=state_store,
        operator_memory=InMemoryOperatorMemoryStore(),
        models=(
            _Model(identity="model-a", family="family-a", result=proposal),
            _Model(identity="model-b", family="family-b", result=proposal),
        ),
        now=lambda: _NOW,
    )

    record = await runtime.coordinator.review(_review_input())

    assert record.state is PostTurnReviewState.ROUTED
    drafts = await runtime.memory_proposals.list()
    assert len(drafts) == 1
    assert drafts[0].state.value == "draft"
    audits = tuple(state_store.audit_entries)
    assert len(audits) == 1
    assert audits[0]["entry"]["mode"] == "shadow"
    assert audits[0]["entry"]["action_kind"] == "operator-memory.proposed"


async def test_runtime_records_unavailable_reviewer_without_routing() -> None:
    runtime = build_post_turn_review_runtime(
        state_store=InMemoryStateStore(),
        operator_memory=InMemoryOperatorMemoryStore(),
        now=lambda: _NOW,
    )

    record = await runtime.coordinator.review(_review_input())

    assert record.state is PostTurnReviewState.ABSTAINED
    assert record.reasons == ("reviewer_unavailable",)
    assert await runtime.memory_proposals.list() == ()


def _resolved_models(*, secondary_family: str) -> ResolvedModels:
    return ResolvedModels(
        schema_version="1",
        region="example-region",
        subscription_id="example-subscription",
        deployer_object_id="example-principal",
        mixed_model_mode="required",
        capabilities=(
            ResolvedCapability(
                name="t2.reasoner.primary",
                status=CapabilityStatus.RESOLVED,
                publisher="publisher-a",
                family="family-a",
                sku="standard",
                capacity_tpm=1_000,
                invocation="always",
            ),
            ResolvedCapability(
                name="t2.reasoner.secondary",
                status=CapabilityStatus.RESOLVED,
                publisher="publisher-b",
                family=secondary_family,
                sku="standard",
                capacity_tpm=1_000,
                invocation="always",
            ),
        ),
    )


async def test_azure_models_require_two_distinct_resolved_families() -> None:
    identity = StaticWorkloadIdentity(audience=COGNITIVE_SERVICES_SCOPE)
    async with httpx.AsyncClient() as client:
        models = build_azure_post_turn_models(
            repo_root=Path(__file__).resolve().parents[2],
            resolved_models_path=_resolved_models(secondary_family="family-b").to_json(),
            endpoint="https://example.com",
            identity=identity,
            http_client=client,
        )
        unavailable = build_azure_post_turn_models(
            repo_root=Path(__file__).resolve().parents[2],
            resolved_models_path=_resolved_models(secondary_family="family-a").to_json(),
            endpoint="https://example.com",
            identity=identity,
            http_client=client,
        )

    assert tuple(model.model_family for model in models) == ("family-a", "family-b")
    assert unavailable == ()
