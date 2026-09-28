"""Compose the Azure LLM prompt bundle without widening runtime authority."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from fdai.core.conversation.conversation_preflight import SOCIAL_NARRATOR_CAPABILITY_IDS
from fdai.core.operator_memory import OperatorMemoryStore
from fdai.core.prompts import (
    ComposedPrompt,
    DefaultPromptComposer,
    FileSystemPromptRegistry,
    PromptAblationProfile,
    PromptAssembler,
    PromptReplayManifest,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AzurePromptBundle:
    """One startup-consistent set of composed prompt roles."""

    composer: DefaultPromptComposer
    primary: ComposedPrompt
    proposer: ComposedPrompt
    semantic_judgment: str
    semantic_judgment_manifest: PromptReplayManifest
    semantic_judgment_assembler: PromptAssembler
    semantic_judgment_schema_repair: str
    semantic_judgment_schema_repair_manifest: PromptReplayManifest
    conversation_preflight: str
    conversation_preflight_manifest: PromptReplayManifest
    social_narrators: Mapping[str, str]
    social_narrator_manifests: Mapping[str, PromptReplayManifest]
    critic: str | None
    judge: str | None
    rca: str | None
    rca_manifest: PromptReplayManifest | None


async def compose_azure_prompt_bundle(
    *,
    catalog_root: Path,
    operator_memory_store: OperatorMemoryStore,
    answer_continuity_enabled: bool,
    prompt_ablation_profile: str,
) -> AzurePromptBundle:
    """Compose required prompts and bounded optional roles from one policy."""

    composer = DefaultPromptComposer(
        registry=FileSystemPromptRegistry(catalog_root),
        operator_memory_store=operator_memory_store,
        ablation_profile=PromptAblationProfile.reviewed(prompt_ablation_profile),
    )
    primary = await composer.compose(capability_id="t2.reasoner.primary")
    proposer = await composer.compose(
        capability_id="t2.proposer",
        profile_id=("shadow.t2-proposer-continuity" if answer_continuity_enabled else None),
    )
    semantic_judgment_prompt = await composer.compose(capability_id="semantic.judgment")
    semantic_judgment_schema_repair_prompt = await composer.compose(
        capability_id="semantic.judgment.schema-repair"
    )
    conversation_preflight_prompt = await composer.compose(capability_id="conversation.preflight")
    social_prompts = {
        act.value: await composer.compose(capability_id=capability_id)
        for act, capability_id in SOCIAL_NARRATOR_CAPABILITY_IDS.items()
    }
    rca_prompt = await _optional_composed_prompt(composer, "t2.rca")
    return AzurePromptBundle(
        composer=composer,
        primary=primary,
        proposer=proposer,
        semantic_judgment=semantic_judgment_prompt.system_text,
        semantic_judgment_manifest=semantic_judgment_prompt.replay_manifest(),
        semantic_judgment_assembler=composer.assembler(capability_id="semantic.judgment"),
        semantic_judgment_schema_repair=semantic_judgment_schema_repair_prompt.system_text,
        semantic_judgment_schema_repair_manifest=(
            semantic_judgment_schema_repair_prompt.replay_manifest()
        ),
        conversation_preflight=conversation_preflight_prompt.system_text,
        conversation_preflight_manifest=conversation_preflight_prompt.replay_manifest(),
        social_narrators={
            social_act: prompt.system_text for social_act, prompt in social_prompts.items()
        },
        social_narrator_manifests={
            social_act: prompt.replay_manifest() for social_act, prompt in social_prompts.items()
        },
        critic=await _optional_prompt(composer, "t2.critic"),
        judge=await _optional_prompt(composer, "t1.judge"),
        rca=rca_prompt.system_text if rca_prompt is not None else None,
        rca_manifest=rca_prompt.replay_manifest() if rca_prompt is not None else None,
    )


async def _optional_prompt(
    composer: DefaultPromptComposer,
    capability_id: str,
) -> str | None:
    try:
        composed = await composer.compose(capability_id=capability_id)
    except LookupError:
        _LOGGER.info("optional_prompt_missing", extra={"capability_id": capability_id})
        return None
    _LOGGER.info(
        "optional_prompt_composed",
        extra={
            "capability_id": capability_id,
            "layer_count": len(composed.layer_manifest),
            "token_estimate": composed.token_estimate,
        },
    )
    return composed.system_text


async def _optional_composed_prompt(
    composer: DefaultPromptComposer,
    capability_id: str,
) -> ComposedPrompt | None:
    try:
        return await composer.compose(capability_id=capability_id)
    except LookupError:
        _LOGGER.info("optional_prompt_missing", extra={"capability_id": capability_id})
        return None


__all__ = ["AzurePromptBundle", "compose_azure_prompt_bundle"]
