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
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AzurePromptBundle:
    """One startup-consistent set of composed prompt roles."""

    composer: DefaultPromptComposer
    primary: ComposedPrompt
    proposer: ComposedPrompt
    semantic_judgment: str
    conversation_preflight: str
    social_narrators: Mapping[str, str]
    critic: str | None
    judge: str | None
    rca: str | None


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
        enabled_shadow_pack_ids=(
            frozenset({"answer-continuity"}) if answer_continuity_enabled else frozenset()
        ),
        ablation_profile=PromptAblationProfile.reviewed(prompt_ablation_profile),
    )
    primary = await composer.compose(capability_id="t2.reasoner.primary")
    proposer = await composer.compose(capability_id="t2.proposer")
    semantic_judgment = (await composer.compose(capability_id="semantic.judgment")).system_text
    conversation_preflight = (
        await composer.compose(capability_id="conversation.preflight")
    ).system_text
    social_narrators = {
        act.value: (await composer.compose(capability_id=capability_id)).system_text
        for act, capability_id in SOCIAL_NARRATOR_CAPABILITY_IDS.items()
    }
    return AzurePromptBundle(
        composer=composer,
        primary=primary,
        proposer=proposer,
        semantic_judgment=semantic_judgment,
        conversation_preflight=conversation_preflight,
        social_narrators=social_narrators,
        critic=await _optional_prompt(composer, "t2.critic"),
        judge=await _optional_prompt(composer, "t1.judge"),
        rca=await _optional_prompt(composer, "t2.rca"),
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


__all__ = ["AzurePromptBundle", "compose_azure_prompt_bundle"]
