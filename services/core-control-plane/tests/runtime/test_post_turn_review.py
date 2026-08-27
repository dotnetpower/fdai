from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
from fdai.composition.semantic_query_model_targets import model_target_for_capability
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
from fdai.rule_catalog.schema.model_endpoint import (
    ModelApiStyle,
    ModelAuthKind,
    ModelCapacityUnit,
    ModelDiscoverySource,
    ModelEndpointBinding,
    ModelEndpointCapacity,
    ModelEndpointDiscovery,
    ModelEndpointFeatures,
    ModelProviderKind,
    ModelRouteKind,
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


def _resolved_models(
    *,
    secondary_family: str,
    primary_publisher: str = "OpenAI",
    secondary_publisher: str = "OpenAI",
    endpoint_bindings: tuple[ModelEndpointBinding, ...] = (),
) -> ResolvedModels:
    return ResolvedModels(
        schema_version="1.0.0",
        region="example-region",
        subscription_id="example-subscription",
        deployer_object_id="example-principal",
        mixed_model_mode="required",
        capabilities=(
            ResolvedCapability(
                name="t2.reasoner.primary",
                status=CapabilityStatus.RESOLVED,
                publisher=primary_publisher,
                family="family-a",
                sku="standard",
                capacity_tpm=1_000,
                invocation="always",
            ),
            ResolvedCapability(
                name="t2.reasoner.secondary",
                status=CapabilityStatus.RESOLVED,
                publisher=secondary_publisher,
                family=secondary_family,
                sku="standard",
                capacity_tpm=1_000,
                invocation="always",
            ),
        ),
        endpoint_bindings=endpoint_bindings,
    )


async def test_azure_models_require_two_distinct_resolved_families() -> None:
    identity = StaticWorkloadIdentity(audience=COGNITIVE_SERVICES_SCOPE)
    async with httpx.AsyncClient() as client:
        models = build_azure_post_turn_models(
            repo_root=Path(__file__).resolve().parents[4],
            resolved_models_path=_resolved_models(secondary_family="family-b").to_json(),
            endpoint="https://example.com",
            endpoint_resolver=lambda _: "https://example.com",
            identity=identity,
            http_client=client,
        )
        unavailable = build_azure_post_turn_models(
            repo_root=Path(__file__).resolve().parents[4],
            resolved_models_path=_resolved_models(secondary_family="family-a").to_json(),
            endpoint="https://example.com",
            endpoint_resolver=lambda _: "https://example.com",
            identity=identity,
            http_client=client,
        )

    assert tuple(model.model_family for model in models) == ("family-a", "family-b")
    assert unavailable == ()


def _endpoint_binding(
    *,
    capability: str,
    provider_kind: ModelProviderKind,
    api_style: ModelApiStyle,
    endpoint_ref: str,
    publisher: str,
    family: str,
) -> ModelEndpointBinding:
    return ModelEndpointBinding(
        binding_id=f"direct:{capability}",
        capability=capability,
        provider_kind=provider_kind,
        route_kind=ModelRouteKind.DIRECT,
        api_style=api_style,
        endpoint_ref=endpoint_ref,
        deployment=capability,
        api_version="2024-06-01" if api_style is ModelApiStyle.AZURE_OPENAI else None,
        auth_kind=ModelAuthKind.ENTRA,
        auth_audience=COGNITIVE_SERVICES_SCOPE,
        publisher=publisher,
        family=family,
        version="1",
        capacity=ModelEndpointCapacity(unit=ModelCapacityUnit.TPM, value=1_000),
        features=ModelEndpointFeatures(streaming=True, structured_output=True),
        discovery=ModelEndpointDiscovery(
            source=ModelDiscoverySource.AZURE_MANAGEMENT,
            resource_ref_digest="a" * 64,
            verified_at=_NOW,
        ),
    )


async def test_azure_models_route_secondary_to_foundry_binding() -> None:
    primary_ref = "azure-openai:oai-fdai"
    secondary_ref = "azure-foundry:aif-fdai-models"
    primary_endpoint = "https://oai-fdai.openai.azure.com"
    secondary_endpoint = "https://aif-fdai-models.services.ai.azure.com"
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"kind":"none","reason":"no_improvement"}'}}]
            },
        )

    resolved = _resolved_models(
        secondary_family="family-b",
        secondary_publisher="MistralAI",
        endpoint_bindings=(
            _endpoint_binding(
                capability="t2.reasoner.primary",
                provider_kind=ModelProviderKind.AZURE_OPENAI,
                api_style=ModelApiStyle.AZURE_OPENAI,
                endpoint_ref=primary_ref,
                publisher="OpenAI",
                family="family-a",
            ),
            _endpoint_binding(
                capability="t2.reasoner.secondary",
                provider_kind=ModelProviderKind.AZURE_FOUNDRY,
                api_style=ModelApiStyle.OPENAI_V1,
                endpoint_ref=secondary_ref,
                publisher="MistralAI",
                family="family-b",
            ),
        ),
    )
    endpoints = {
        primary_ref: primary_endpoint,
        secondary_ref: secondary_endpoint,
    }
    identity = StaticWorkloadIdentity(audience=COGNITIVE_SERVICES_SCOPE)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        models = build_azure_post_turn_models(
            repo_root=Path(__file__).resolve().parents[4],
            resolved_models_path=resolved.to_json(),
            endpoint=primary_endpoint,
            endpoint_resolver=endpoints.__getitem__,
            identity=identity,
            http_client=client,
        )
        await models[0].propose(_review_input())
        await models[1].propose(_review_input())

    assert [request.url.path for request in requests] == [
        "/openai/deployments/t2.reasoner.primary/chat/completions",
        "/v1/chat/completions",
    ]
    assert requests[1].url.host == "aif-fdai-models.services.ai.azure.com"
    assert b'"model":"t2.reasoner.secondary"' in requests[1].content


def test_semantic_target_routes_foundry_primary_through_endpoint_resolver() -> None:
    endpoint_ref = "azure-foundry:aif-fdai-models"
    endpoint = "https://aif-fdai-models.services.ai.azure.com"
    resolved = _resolved_models(
        secondary_family="family-b",
        primary_publisher="MistralAI",
        endpoint_bindings=(
            _endpoint_binding(
                capability="t2.reasoner.primary",
                provider_kind=ModelProviderKind.AZURE_FOUNDRY,
                api_style=ModelApiStyle.OPENAI_V1,
                endpoint_ref=endpoint_ref,
                publisher="MistralAI",
                family="family-a",
            ),
        ),
    )

    target = model_target_for_capability(
        resolved,
        "t2.reasoner.primary",
        endpoint="https://oai-fdai.openai.azure.com",
        endpoint_resolver={endpoint_ref: endpoint}.__getitem__,
    )

    assert target is not None
    assert target.endpoint == endpoint
    assert target.api_style is ModelApiStyle.OPENAI_V1


async def test_azure_models_reject_partner_capability_without_endpoint_binding() -> None:
    resolved = _resolved_models(
        secondary_family="family-b",
        secondary_publisher="MistralAI",
    )
    identity = StaticWorkloadIdentity(audience=COGNITIVE_SERVICES_SCOPE)
    async with httpx.AsyncClient() as client:
        models = build_azure_post_turn_models(
            repo_root=Path(__file__).resolve().parents[4],
            resolved_models_path=resolved.to_json(),
            endpoint="https://oai-fdai.openai.azure.com",
            endpoint_resolver=lambda _: "https://oai-fdai.openai.azure.com",
            identity=identity,
            http_client=client,
        )

    assert models == ()
