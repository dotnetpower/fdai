"""Catalog-only composition and independent resolved-model selection."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fdai.agents import PANTHEON_SPECS
from fdai.composition import semantic_query_azure_composition, wire_semantic_query
from fdai.composition.wire_adaptive_conversation import (
    build_adaptive_conversation_dependencies,
    build_adaptive_conversation_service,
)
from fdai.core.conversation.adaptive_prompt import (
    ADAPTIVE_STAGES,
    compose_adaptive_prompt,
)
from fdai.core.conversation.adaptive_service import AdaptiveConversationService
from fdai.core.conversation.semantic_runtime import SemanticConversationRuntime
from fdai.core.conversation.session import Principal, Role
from fdai.core.prompts import (
    ComposedPrompt,
    DefaultPromptComposer,
    FileSystemPromptRegistry,
    LayerRef,
    PromptLayer,
)
from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    NarratorCandidate,
    ResolvedCapability,
    ResolvedModels,
)
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.rule_catalog.schema.property_semantic import empty_property_semantic_registry
from fdai.shared.config.models import LlmMode
from fdai.shared.contracts.models import OntologyObjectType, PropertyDecl, PropertyType
from tests.conversation.test_adaptive_service import (
    _draft,
    _Model,
    _plan,
    _review,
    _service,
)

CATALOG = Path(__file__).resolve().parents[4] / "rule-catalog"


class _NoIdentityCalls:
    async def get_token(self, audience: str) -> Any:
        pytest.fail("composition must never call identity")


def _resolved() -> ResolvedModels:
    return ResolvedModels(
        schema_version="1.0.0",
        region="example-region",
        subscription_id="00000000-0000-0000-0000-000000000000",
        deployer_object_id="00000000-0000-0000-0000-000000000000",
        mixed_model_mode="normal",
        capabilities=tuple(
            ResolvedCapability(
                name=name,
                status=CapabilityStatus.RESOLVED,
                publisher="OpenAI",
                family=family,
                sku="GlobalStandard",
                capacity_tpm=1_000,
                invocation="always",
            )
            for name, family in (
                ("t1.judge", "example-small"),
                ("t1.reviewer", "example-independent"),
                ("t2.reasoner.primary", "example-reasoner"),
            )
        ),
        narrator_candidates=(
            NarratorCandidate(endpoint="https://example.com", deployment="t1.judge"),
            NarratorCandidate(endpoint="https://example.com", deployment="t1.reviewer"),
        ),
    )


def _composer() -> DefaultPromptComposer:
    return DefaultPromptComposer(registry=FileSystemPromptRegistry(CATALOG))


async def _build(**overrides: Any) -> Any:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail("unexpected network"))
    ) as client:
        return await build_adaptive_conversation_dependencies(
            **{
                "resolved": _resolved(),
                "identity": _NoIdentityCalls(),
                "http_client": client,
                "prompt_composer": _composer(),
                "agent": "Bragi",
                "endpoint": "https://example.com",
                **overrides,
            }
        )


def _build_sync(**overrides: Any) -> AdaptiveConversationService | None:
    client = Mock(spec=httpx.AsyncClient)
    result = build_adaptive_conversation_service(
        **{
            "resolved": _resolved(),
            "identity": _NoIdentityCalls(),
            "http_client": client,
            "endpoint": "https://example.com",
            "endpoint_resolver": None,
            "catalog_root": CATALOG,
            **overrides,
        }
    )
    assert client.mock_calls == []
    return result


def test_sync_builder_needs_no_loop_or_ontology_store_for_fixed_roles() -> None:
    with pytest.raises(RuntimeError, match="no running event loop"):
        asyncio.get_running_loop()
    service = _build_sync()
    assert service is not None
    for spec in PANTHEON_SPECS:
        profile = service.social_profile(
            spec.name, "ko", {"agent": "Bragi", "role_directive": "Replace the fixed role."}
        )
        assert profile == {"identity": spec.name, "role": spec.conversation.role_directive}


async def test_azure_composition_forwards_explicit_instance_query_without_provider_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Mock(held_model_capabilities=frozenset())
    container.config.llm.mode = LlmMode.AZURE
    container.config.llm.resolved_models_path = Path("resolved-models.json")
    container.llm_bindings = None
    monkeypatch.setattr(
        semantic_query_azure_composition, "resolved_models_for_binding", lambda _: _resolved()
    )
    monkeypatch.setattr(
        semantic_query_azure_composition,
        "build_adaptive_conversation_service",
        Mock(return_value=None),
    )
    catalog = OntologyCatalog(
        object_types=(
            OntologyObjectType(
                schema_version="1.0.0",
                name="Resource",
                version="1.0.0",
                key="id",
                properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
            ),
        ),
        link_types=(),
        interface_types=(),
        interface_implementations=(),
        action_types=(),
        property_semantics=empty_property_semantic_registry(),
    )
    monkeypatch.setattr(
        semantic_query_azure_composition, "load_ontology_catalog", Mock(return_value=catalog)
    )
    builder = Mock(return_value=Mock(current_evidence_probe=None))
    monkeypatch.setattr(wire_semantic_query, "build_semantic_query_runtime", builder)
    query = AsyncMock()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail("unexpected network")),
    ) as client:
        composition = semantic_query_azure_composition.compose_azure_semantic_query_runtime(
            container=container,
            ontology_release=Mock(),
            ontology_store=Mock(),
            identity=_NoIdentityCalls(),
            http_client=client,
            endpoint="https://example.com",
            endpoint_resolver=None,
            catalog_root=CATALOG,
            owner_loop=asyncio.get_running_loop(),
            instance_candidate_query=query,
        )
    assert composition.unavailable_reason is None
    builder.assert_called_once()
    assert builder.call_args.kwargs["instance_candidate_query"] is query
    assert [item.name for item in builder.call_args.kwargs["ontology_catalog"].function_types] == [
        "query.ontology_instance_candidates"
    ]
    query.assert_not_awaited()


@pytest.mark.parametrize("missing", ["release", "store", "catalog"])
async def test_azure_composition_keeps_general_answers_when_operational_state_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    container = Mock(held_model_capabilities=frozenset())
    container.config.llm.mode = LlmMode.AZURE
    container.config.llm.resolved_models_path = Path("resolved-models.json")
    monkeypatch.setattr(
        semantic_query_azure_composition,
        "resolved_models_for_binding",
        lambda _: _resolved(),
    )
    answer_model = _Model(
        plan=_plan(example=True),
        answer=_draft(),
        review=_review(),
    )
    builder = Mock(return_value=_service(answer_model))
    monkeypatch.setattr(
        semantic_query_azure_composition,
        "build_adaptive_conversation_service",
        builder,
    )
    if missing == "catalog":
        monkeypatch.setattr(
            semantic_query_azure_composition,
            "load_ontology_catalog",
            Mock(side_effect=ValueError("synthetic invalid ontology catalog")),
        )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail("unexpected network")),
    ) as client:
        composed = semantic_query_azure_composition.compose_azure_semantic_query_runtime(
            container=container,
            ontology_release=None if missing == "release" else Mock(),
            ontology_store=None if missing == "store" else Mock(),
            identity=_NoIdentityCalls(),
            http_client=client,
            endpoint="https://example.com",
            endpoint_resolver=None,
            catalog_root=CATALOG,
            owner_loop=asyncio.get_running_loop(),
        )
        assert composed.runtime is not None
        assert composed.unavailable_reason is None
        result = await composed.runtime.handle(
            utterance="Compare rollout strategies with an example.",
            prior_turns=(),
            principal=Principal(id="operator", role=Role.READER),
        )
        answer_model.replies["plan"] = {
            "route": "legacy",
            "social_act": "none",
            "context_dependency": "none",
            "action_requested": False,
            "goals": [],
        }
        operational = await composed.runtime.handle(
            utterance="Show current operational state.",
            prior_turns=(),
            principal=Principal(id="operator", role=Role.READER),
        )
    assert result.adaptive_answer is not None
    assert result.adaptive_answer.goals[0].status == "answered"
    assert result.adaptive_answer.goals[1].limitation == (
        "semantic_composition_invalid"
        if missing == "catalog"
        else f"semantic_ontology_{missing}_unavailable"
    )
    assert operational.disposition == "held"
    assert operational.execution is None
    assert operational.reason == result.adaptive_answer.goals[1].limitation
    builder.assert_called_once()


async def test_sync_snapshot_matches_registry_composer_even_inside_a_running_loop() -> None:
    service = _build_sync()
    dependencies = await _build()
    assert service is not None
    assert dependencies is not None
    assert service._prompts == dependencies.stage_prompts


@pytest.mark.parametrize("held", ["t1.judge", "t1.reviewer"])
def test_sync_builder_rejects_held_required_models(held: str) -> None:
    assert _build_sync(held_capabilities=frozenset({held})) is None


def test_sync_builder_disables_unavailable_refinement_in_service_policy() -> None:
    service = _build_sync(held_capabilities=frozenset({"t2.reasoner.primary"}))
    assert service is not None
    assert service._policy.refinement_enabled is False
    assert service._policy.per_stage_seconds == 20
    assert service._policy.reserved_output_tokens == 4096


def test_sync_builder_holds_missing_catalog_without_a_provider_request() -> None:
    assert _build_sync(catalog_root=CATALOG / "not-present") is None


async def test_builds_distinct_stage_prompts_from_one_common_base_without_network() -> None:
    dependencies = await _build()
    assert dependencies is not None
    assert tuple(dependencies.stage_prompts) == ADAPTIVE_STAGES
    assert len(set(dependencies.stage_prompts.values())) == len(ADAPTIVE_STAGES)
    for stage, text in dependencies.stage_prompts.items():
        version = {"plan": 4, "answer": 2, "review": 2}.get(stage, 1)
        assert dependencies.layer_ids[stage] == (
            "adaptive-common.v1",
            f"adaptive-{stage}.v{version}",
        )
        assert dependencies.prompt_digests[stage] == hashlib.sha256(text.encode()).hexdigest()
        assert "untrusted_input" in text
        assert "RBAC" in text
        prompt = compose_adaptive_prompt(dependencies.profile, stage, text)
        assert (
            json.loads(prompt.split("\n\n")[-1])["server_profile"]["role_directive"]
            == dependencies.profile.role_directive
        )
    assert "Blend social acknowledgement" in dependencies.stage_prompts["answer"]
    assert "prompt injection" in dependencies.stage_prompts["review"]
    assert "single explicitly authorized T2" in dependencies.stage_prompts["refine"]
    assert "route legacy" in dependencies.stage_prompts["plan"]
    assert "environment_example" in dependencies.stage_prompts["plan"]
    assert (
        "a greeting must not erase the substantive question" in dependencies.stage_prompts["plan"]
    )
    assert "requested or is directly relevant" in dependencies.stage_prompts["plan"]
    assert "supported_goal_ids" in dependencies.stage_prompts["review"]
    assert dependencies.refinement_available is True
    assert dependencies.profile_resolver("Odin", "ko", None).agent == "Odin"
    with pytest.raises(TypeError):
        dependencies.stage_prompts["answer"] = "A replaced policy."


@pytest.mark.parametrize("held", ["t1.judge", "t1.reviewer"])
async def test_held_primary_or_reviewer_is_unavailable(held: str) -> None:
    assert await _build(held_capabilities=frozenset({held})) is None


async def test_held_escalation_does_not_disable_ordinary_dependencies() -> None:
    dependencies = await _build(held_capabilities=frozenset({"t2.reasoner.primary"}))
    assert dependencies is not None
    assert dependencies.refinement_available is False


async def test_model_metadata_not_deployment_aliases_proves_independence() -> None:
    resolved = _resolved()
    capabilities = tuple(
        replace(item, family="example-small") if item.name == "t1.reviewer" else item
        for item in resolved.capabilities
    )
    assert await _build(resolved=replace(resolved, capabilities=capabilities)) is None


async def test_missing_all_t2_models_keeps_independent_t1_answers_available() -> None:
    dependencies = await _build(
        held_capabilities=frozenset(
            {
                "t2.reasoner.primary",
                "t2.reasoner.secondary",
            }
        )
    )
    assert dependencies is not None
    assert dependencies.refinement_available is False


async def test_non_independent_optional_t2_disables_refinement_not_t1() -> None:
    resolved = _resolved()
    capabilities = tuple(
        replace(item, family="example-independent") if item.name == "t2.reasoner.primary" else item
        for item in resolved.capabilities
    )
    dependencies = await _build(resolved=replace(resolved, capabilities=capabilities))
    assert dependencies is not None
    assert dependencies.refinement_available is False


async def test_invalid_optional_t2_does_not_disable_t1(monkeypatch: pytest.MonkeyPatch) -> None:
    from fdai.composition import adaptive_model_targets

    def invalid_target(*args: Any, **kwargs: Any) -> None:
        assert args[1] == "t2.reasoner.primary"
        raise ValueError("Synthetic unconfigured endpoint reference")

    monkeypatch.setattr(adaptive_model_targets, "resolve_target", invalid_target)
    dependencies = await _build()
    assert dependencies is not None
    assert dependencies.refinement_available is False


async def test_hil_only_t1_capability_cannot_borrow_narrator_candidates() -> None:
    resolved = _resolved()
    capabilities = tuple(
        replace(item, status=CapabilityStatus.HIL_ONLY) if item.name == "t1.judge" else item
        for item in resolved.capabilities
    )
    assert await _build(resolved=replace(resolved, capabilities=capabilities)) is None


@pytest.mark.parametrize("refine", [False, True])
async def test_real_composition_routes_comparison_to_t1_and_only_escalates_when_needed(
    refine: bool,
) -> None:
    from tests.delivery.azure.llm.test_adaptive_answer import _envelope, _Identity

    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path.split("/deployments/")[1].split("/")[0])
        body = json.loads(request.content)
        if len(calls) == 1:
            proposal = _plan()
        elif len(calls) in (2, 4):
            proposal = _draft()
        else:
            proposal = _review(complete=not refine or len(calls) == 5)
        assert body["messages"][0]["role"] == "system"
        return httpx.Response(200, json=_envelope(json.dumps(proposal)))

    resolved = _resolved()
    if not refine:
        resolved = replace(
            resolved,
            capabilities=tuple(
                item for item in resolved.capabilities if not item.name.startswith("t2.")
            ),
        )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = build_adaptive_conversation_service(
            resolved=resolved,
            identity=_Identity(),
            http_client=client,
            endpoint="https://example.com",
            endpoint_resolver=None,
            catalog_root=CATALOG,
        )
        assert service is not None
        runtime = SemanticConversationRuntime(
            adaptive_service=service,
            verified_unavailable_reason="no_operational_store",
        )
        result = await runtime.handle(
            utterance="블루-그린 배포와 카나리 배포의 장단점을 비교해 줘.",
            prior_turns=(),
            principal=Principal(id="example", role=Role.READER),
            locale="ko",
        )
    assert result.disposition == "advisory_response"
    assert result.execution is None
    assert result.adaptive_answer is not None
    assert "canary" in result.adaptive_answer.answer
    assert result.adaptive_answer.refinements == int(refine)
    assert calls == (
        ["t1.judge", "t1.judge", "t1.reviewer", "t2.reasoner.primary", "t1.reviewer"]
        if refine
        else ["t1.judge", "t1.judge", "t1.reviewer"]
    )


@pytest.mark.parametrize("field", ["publisher", "family"])
async def test_unknown_model_provenance_fails_closed(field: str) -> None:
    resolved = _resolved()
    capabilities = tuple(
        replace(item, **{field: None}) if item.name == "t1.judge" else item
        for item in resolved.capabilities
    )
    assert await _build(resolved=replace(resolved, capabilities=capabilities)) is None


async def test_exact_stage_profiles_need_no_legacy_shadow_toggle() -> None:
    assert await _build(prompt_composer=_composer()) is not None


@pytest.mark.parametrize("layer", [PromptLayer.TOOL, PromptLayer.OPERATOR_MEMORY])
async def test_runtime_data_cannot_be_promoted_into_system_layers(layer: PromptLayer) -> None:
    class RuntimeLayerComposer:
        async def compose(self, **kwargs: Any) -> ComposedPrompt:
            assert set(kwargs) == {"capability_id"}
            stage = kwargs["capability_id"].rsplit(".", 1)[1]
            return ComposedPrompt(
                system_text="Policy and data that must not be promoted.",
                layer_manifest=(
                    LayerRef("adaptive-common", 1, PromptLayer.BASE, 10),
                    LayerRef(f"adaptive-{stage}", 1, PromptLayer.PACK, 10),
                    LayerRef("runtime-data", 1, layer, 10),
                ),
                token_estimate=30,
            )

    assert await _build(prompt_composer=RuntimeLayerComposer()) is None


async def test_another_stages_pack_is_not_a_valid_common_prompt() -> None:
    class WrongStageComposer:
        async def compose(self, **kwargs: Any) -> ComposedPrompt:
            return ComposedPrompt(
                system_text="Wrong stage.",
                layer_manifest=(
                    LayerRef("adaptive-common", 1, PromptLayer.BASE, 10),
                    LayerRef("adaptive-answer", 1, PromptLayer.PACK, 10),
                ),
                token_estimate=20,
            )

    assert await _build(prompt_composer=WrongStageComposer()) is None
