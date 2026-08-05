from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from fdai.delivery.operator_api.routes.chat_inventory import (
    InventoryChatTools,
    render_inventory_answer,
)
from fdai.delivery.operator_api.routes.chat_inventory_ontology import (
    inventory_query_function_type,
    project_inventory_function_result,
)
from fdai.delivery.operator_api.routes.chat_inventory_semantic_retrieval import (
    EmbeddingInventorySemanticResolver,
    InventorySemanticConfig,
    InventorySemanticKind,
    InventorySemanticMatch,
)
from fdai.shared.contracts.models import (
    OntologyDeclarationKind,
    OntologyDeclarationRef,
    OntologyRelease,
    OntologyTypeRef,
)

_RELEASE_DIGEST = "sha256:" + "a" * 64
_DECLARATION_DIGEST = "sha256:" + "b" * 64


def _target_ref() -> OntologyTypeRef:
    release = OntologyRelease(
        digest=_RELEASE_DIGEST,
        declarations=(
            OntologyDeclarationRef(
                kind=OntologyDeclarationKind.FUNCTION,
                name="inventory.select_resources",
                version="1.0.0",
                declaration_digest=_DECLARATION_DIGEST,
            ),
        ),
    )
    return release.type_ref(OntologyDeclarationKind.FUNCTION, "inventory.select_resources")


class ControlledEmbedder:
    async def embed(self, text: str) -> Sequence[float]:
        normalized = text.casefold()
        if normalized == "machines still serving traffic":
            return (1.0, 0.0, 0.0)
        if normalized == "ambiguous power wording":
            return (1.0, 1.0, 0.0)
        if normalized.startswith("state:running"):
            return (1.0, 0.0, 0.0)
        if normalized.startswith("state:inactive"):
            return (0.0, 1.0, 0.0)
        if normalized.startswith("operation:start"):
            return (0.0, 0.0, 1.0)
        return (-1.0, -1.0, -1.0)


class FailingEmbedder:
    async def embed(self, text: str) -> Sequence[float]:
        del text
        raise RuntimeError("embedding unavailable")


async def test_description_embedding_returns_non_authoritative_state_candidate() -> None:
    resolver = EmbeddingInventorySemanticResolver(
        embedder=ControlledEmbedder(),
        target_ref=_target_ref(),
        config=InventorySemanticConfig(score_threshold=0.6, max_candidates=3),
    )

    matches = await resolver.resolve("machines still serving traffic")

    assert matches
    assert matches[0].kind is InventorySemanticKind.STATE
    assert matches[0].concept_id == "running"
    assert matches[0].authority == "candidate_only"
    assert matches[0].catalog_digest.startswith("sha256:")
    assert matches[0].target_ref.catalog_digest == _RELEASE_DIGEST
    assert matches[0].input_digest.startswith("sha256:")
    assert matches[0].candidate_digest.startswith("sha256:")


async def test_semantic_ties_have_stable_concept_order() -> None:
    resolver = EmbeddingInventorySemanticResolver(
        embedder=ControlledEmbedder(),
        target_ref=_target_ref(),
        config=InventorySemanticConfig(score_threshold=0.6, max_candidates=3),
    )

    matches = await resolver.resolve("ambiguous power wording")

    assert [(item.kind.value, item.concept_id) for item in matches[:2]] == [
        ("state", "inactive"),
        ("state", "running"),
    ]


async def test_embedding_failure_returns_no_candidate() -> None:
    resolver = EmbeddingInventorySemanticResolver(
        embedder=FailingEmbedder(),
        target_ref=_target_ref(),
    )

    assert await resolver.resolve("machines still serving traffic") == ()


class FixedResolver:
    async def resolve(self, prompt: str) -> tuple[InventorySemanticMatch, ...]:
        del prompt
        return (
            InventorySemanticMatch(
                kind=InventorySemanticKind.STATE,
                concept_id="running",
                score=0.91,
                catalog_digest="sha256:" + "a" * 64,
                target_ref=_target_ref(),
                input_digest="sha256:" + "c" * 64,
                candidate_digest="sha256:" + "d" * 64,
                labels={"en": "Running", "ko": "실행 중"},
            ),
            InventorySemanticMatch(
                kind=InventorySemanticKind.STATE,
                concept_id="inactive",
                score=0.89,
                catalog_digest="sha256:" + "a" * 64,
                target_ref=_target_ref(),
                input_digest="sha256:" + "c" * 64,
                candidate_digest="sha256:" + "e" * 64,
                labels={"en": "Not running", "ko": "실행 중 아님"},
            ),
        )


@pytest.mark.parametrize(
    "prompt",
    (
        "안꺼진 vm",
        "VMs that have not been powered down",
        "started VM",
        "전원이 내려가지 않은 가상 머신",
        "작업을 처리하고 있는 가상 머신",
        "전원이 유지되는 VM",
        "계속 서비스 중인 VM",
        "기동된 VM",
        "virtual machines still serving workloads",
        "VMs remaining online",
        "virtual machines that continue processing work",
        "virtual machines brought online",
        "VMs available for processing",
    ),
)
async def test_unpromoted_semantic_surface_clarifies_without_provider_read(prompt: str) -> None:
    provider_calls = 0

    async def provider(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal provider_calls
        del args, kwargs
        provider_calls += 1
        raise AssertionError("semantic candidates must not read provider data")

    evidence = await InventoryChatTools(
        provider,
        semantic_resolver=FixedResolver(),
    ).resolve(prompt, principal_id="reader")

    assert evidence is not None
    assert evidence["result"]["status"] == "clarification"
    assert evidence["result"]["reason"] == "inventory_semantic_confirmation_required"
    assert evidence["result"]["semantic_candidates"][0]["authority"] == "candidate_only"
    function_result = project_inventory_function_result(evidence["result"])
    Draft202012Validator(inventory_query_function_type().output_schema).validate(function_result)
    answer = render_inventory_answer(evidence, locale="ko")
    assert answer is not None
    assert "Azure inventory를 조회하지 않았습니다" in answer
    assert "현재 상태: 실행 중" in answer
    assert "0.91" not in answer
    assert provider_calls == 0


async def test_mutation_wording_never_becomes_semantic_inventory_read() -> None:
    provider_calls = 0

    async def provider(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal provider_calls
        del args, kwargs
        provider_calls += 1
        return {}

    evidence = await InventoryChatTools(
        provider,
        semantic_resolver=FixedResolver(),
    ).resolve("VM을 시작해줘", principal_id="reader")

    assert evidence is None
    assert provider_calls == 0


async def test_causal_diagnosis_never_becomes_semantic_inventory_retrieval() -> None:
    class RejectResolver:
        async def resolve(self, prompt: str) -> tuple[InventorySemanticMatch, ...]:
            del prompt
            raise AssertionError("causal diagnosis must not call semantic retrieval")

    provider_calls = 0

    async def provider(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal provider_calls
        del args, kwargs
        provider_calls += 1
        return {}

    evidence = await InventoryChatTools(
        provider,
        semantic_resolver=RejectResolver(),
    ).resolve("What is the root cause of this unavailable VM?", principal_id="reader")

    assert evidence is None
    assert provider_calls == 0


async def test_diagnosis_wording_is_not_hijacked_by_semantic_inventory() -> None:
    provider_calls = 0

    async def provider(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal provider_calls
        del args, kwargs
        provider_calls += 1
        return {}

    evidence = await InventoryChatTools(
        provider,
        semantic_resolver=FixedResolver(),
    ).resolve("VM이 느린 원인이 뭐야", principal_id="reader")

    assert evidence is None
    assert provider_calls == 0


async def test_exact_followup_after_clarification_runs_deterministic_query() -> None:
    provider_calls = 0

    async def provider(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal provider_calls
        del args, kwargs
        provider_calls += 1
        return {
            "resources": [
                {
                    "id": "vm-running",
                    "type": "compute.vm",
                    "name": "vm-running",
                    "status": "VM running",
                    "status_source": "operational",
                },
                {
                    "id": "vm-stopped",
                    "type": "compute.vm",
                    "name": "vm-stopped",
                    "status": "VM stopped",
                    "status_source": "operational",
                },
            ],
            "links": [],
            "freshness": "fresh",
            "source": "test-inventory",
        }

    tools = InventoryChatTools(provider, semantic_resolver=FixedResolver())

    first = await tools.resolve("전원이 유지되는 VM", principal_id="reader")
    second = await tools.resolve("running VM list", principal_id="reader")

    assert first is not None
    assert first["result"]["status"] == "clarification"
    assert second is not None
    assert second["result"]["status"] == "matched"
    assert [item["name"] for item in second["result"]["resources"]] == ["vm-running"]
    assert provider_calls == 1
