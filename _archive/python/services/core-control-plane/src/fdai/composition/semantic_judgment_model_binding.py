"""Build Azure semantic-judgment models from one bounded prompt and target set."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

import httpx
from fdai_service_contracts.semantic_judgment import SemanticJudgmentTier

from fdai.core.conversation.semantic_judgment import (
    SemanticJudgmentBinding,
    SemanticJudgmentModel,
)
from fdai.core.prompts import PromptAssembler, PromptReplayManifest
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.delivery.azure.llm.semantic_judgment import (
    AzureOpenAISemanticJudgmentModel,
    AzureOpenAISemanticJudgmentModelConfig,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity


def build_semantic_judgment_model(
    *,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    candidates: tuple[ModelRequestTarget, ...],
    system_prompt: str,
    system_prompt_manifest: PromptReplayManifest | None,
    owner_loop: asyncio.AbstractEventLoop,
    preflight_system_prompt: str | None = None,
    preflight_prompt_manifest: PromptReplayManifest | None = None,
    social_narrator_system_prompts: Mapping[str, str] | None = None,
    social_narrator_prompt_manifests: Mapping[str, PromptReplayManifest] | None = None,
    intent_hardening_enabled: bool = False,
    system_prompt_assembler: PromptAssembler | None = None,
) -> AzureOpenAISemanticJudgmentModel:
    """Return one loop-bound T1 or T2 semantic model without selecting its role."""

    return AzureOpenAISemanticJudgmentModel(
        identity=identity,
        http_client=http_client,
        config=AzureOpenAISemanticJudgmentModelConfig(
            candidates=candidates,
            system_prompt=system_prompt,
            system_prompt_manifest=system_prompt_manifest,
            preflight_system_prompt=preflight_system_prompt,
            preflight_prompt_manifest=preflight_prompt_manifest,
            social_narrator_system_prompts=dict(social_narrator_system_prompts or {}),
            social_narrator_prompt_manifests=dict(social_narrator_prompt_manifests or {}),
            intent_hardening_enabled=intent_hardening_enabled,
            system_prompt_assembler=system_prompt_assembler,
        ),
        owner_loop=owner_loop,
    )


def target_records(targets: Sequence[ModelRequestTarget]) -> list[dict[str, object]]:
    """Return content-free target identity records for configuration digests."""

    return [
        {
            "endpoint": target.endpoint,
            "deployment": target.deployment,
            "api_version": target.api_version,
            "api_style": target.api_style.value,
            "route_kind": target.route_kind.value,
            "binding_id": target.binding_id,
        }
        for target in targets
    ]


def semantic_judgment_binding(
    *,
    tier: SemanticJudgmentTier,
    model: SemanticJudgmentModel | None,
    model_config_digest: str,
    prompt_digest: str | None,
) -> SemanticJudgmentBinding | None:
    """Bind one available model only when its prompt provenance is complete."""

    if model is None or prompt_digest is None:
        return None
    return SemanticJudgmentBinding(
        tier=tier,
        model=model,
        model_config_digest=model_config_digest,
        prompt_digest=prompt_digest,
    )


__all__ = [
    "build_semantic_judgment_model",
    "semantic_judgment_binding",
    "target_records",
]
