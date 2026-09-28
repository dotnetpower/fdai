"""Production factory wiring for no-authority semantic judgment."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping

import httpx
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.semantic_judgment import SemanticJudgmentTier

from fdai.core.conversation.conversation_preflight import (
    ConversationPreflightBinding,
    ConversationPreflightBoundary,
    SocialResponseNarratorBinding,
)
from fdai.core.conversation.semantic_judgment import SemanticJudgmentBoundary
from fdai.core.prompts import PromptAssembler, PromptReplayManifest
from fdai.rule_catalog.schema.llm_resolver import ResolvedModels
from fdai.shared.providers.workload_identity import WorkloadIdentity

from .semantic_judgment_model_binding import (
    build_semantic_judgment_model,
    semantic_judgment_binding,
    target_records,
)
from .semantic_query_model_targets import t1_model_targets, t2_model_targets

SemanticJudgmentFactory = Callable[[asyncio.AbstractEventLoop], SemanticJudgmentBoundary]
_LOGGER = logging.getLogger(__name__)


def build_azure_semantic_judgment_factory(
    *,
    resolved: ResolvedModels,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    endpoint: str | None,
    endpoint_resolver: Callable[[str], str] | None,
    system_prompt: str | None,
    system_prompt_manifest: PromptReplayManifest | None = None,
    schema_repair_system_prompt: str | None = None,
    schema_repair_prompt_manifest: PromptReplayManifest | None = None,
    preflight_system_prompt: str | None = None,
    preflight_prompt_manifest: PromptReplayManifest | None = None,
    social_narrator_system_prompts: Mapping[str, str] | None = None,
    social_narrator_prompt_manifests: Mapping[str, PromptReplayManifest] | None = None,
    held_capabilities: frozenset[str] = frozenset(),
    intent_hardening_enabled: bool = False,
    system_prompt_assembler: PromptAssembler | None = None,
) -> SemanticJudgmentFactory | None:
    """Return a loop-bound T1/T2 factory or ``None`` when unavailable."""

    if not system_prompt:
        _LOGGER.warning(
            "semantic_judgment_factory_unavailable",
            extra={"reason": "prompt_unavailable", "available_tiers": []},
        )
        return None
    t1_targets = t1_model_targets(
        resolved,
        endpoint=endpoint,
        endpoint_resolver=endpoint_resolver,
        held_capabilities=held_capabilities,
    )
    if not t1_targets:
        _LOGGER.warning(
            "semantic_judgment_factory_unavailable",
            extra={"reason": "t1_target_unavailable", "available_tiers": []},
        )
        return None
    t2_targets = t2_model_targets(
        resolved,
        endpoint=endpoint,
        endpoint_resolver=endpoint_resolver,
        held_capabilities=held_capabilities,
    )
    available_tiers = ["t1"] + (["t2"] if t2_targets else [])
    _LOGGER.info(
        "semantic_judgment_factory_bound",
        extra={"available_tiers": available_tiers},
    )
    prompt_digest = content_digest({"prompt": system_prompt})
    schema_repair_prompt_digest = (
        content_digest({"prompt": schema_repair_system_prompt})
        if schema_repair_system_prompt is not None
        else None
    )
    preflight_prompt_digest = (
        content_digest({"prompt": preflight_system_prompt})
        if preflight_system_prompt is not None
        else None
    )
    narrator_prompts = dict(social_narrator_system_prompts or {})
    social_narrator_prompt_digest = (
        content_digest({"prompts": narrator_prompts}) if narrator_prompts else None
    )
    t1_config_digest = content_digest({"targets": target_records(t1_targets)})
    t2_config_digest = content_digest({"targets": target_records(t2_targets)})

    def factory(owner_loop: asyncio.AbstractEventLoop) -> SemanticJudgmentBoundary:
        primary = build_semantic_judgment_model(
            identity=identity,
            http_client=http_client,
            candidates=t1_targets,
            system_prompt=system_prompt,
            system_prompt_manifest=system_prompt_manifest,
            preflight_system_prompt=preflight_system_prompt,
            preflight_prompt_manifest=preflight_prompt_manifest,
            social_narrator_system_prompts=narrator_prompts,
            social_narrator_prompt_manifests=social_narrator_prompt_manifests,
            intent_hardening_enabled=intent_hardening_enabled,
            system_prompt_assembler=system_prompt_assembler,
            owner_loop=owner_loop,
        )
        escalation = (
            build_semantic_judgment_model(
                identity=identity,
                http_client=http_client,
                candidates=t2_targets,
                system_prompt=system_prompt,
                system_prompt_manifest=system_prompt_manifest,
                preflight_system_prompt=preflight_system_prompt,
                preflight_prompt_manifest=preflight_prompt_manifest,
                intent_hardening_enabled=intent_hardening_enabled,
                owner_loop=owner_loop,
            )
            if t2_targets
            else None
        )
        schema_repair_model = (
            build_semantic_judgment_model(
                identity=identity,
                http_client=http_client,
                candidates=t1_targets,
                system_prompt=schema_repair_system_prompt,
                system_prompt_manifest=schema_repair_prompt_manifest,
                intent_hardening_enabled=True,
                owner_loop=owner_loop,
            )
            if schema_repair_system_prompt is not None
            else None
        )
        return SemanticJudgmentBoundary(
            profile_id="pantheon-conversation",
            profile_version="1.0.0",
            primary=semantic_judgment_binding(
                tier=SemanticJudgmentTier.T1,
                model=primary,
                model_config_digest=t1_config_digest,
                prompt_digest=prompt_digest,
            ),
            schema_repair=semantic_judgment_binding(
                tier=SemanticJudgmentTier.T1,
                model=schema_repair_model,
                model_config_digest=t1_config_digest,
                prompt_digest=schema_repair_prompt_digest,
            ),
            escalation=semantic_judgment_binding(
                tier=SemanticJudgmentTier.T2,
                model=escalation,
                model_config_digest=t2_config_digest,
                prompt_digest=prompt_digest,
            ),
            strict_intent_grounding=intent_hardening_enabled,
            preflight=(
                ConversationPreflightBoundary(
                    binding=ConversationPreflightBinding(
                        model=primary,
                        model_config_digest=t1_config_digest,
                        prompt_digest=preflight_prompt_digest,
                        supports_cancellation=True,
                    ),
                    t2_binding=(
                        ConversationPreflightBinding(
                            model=escalation,
                            model_config_digest=t2_config_digest,
                            prompt_digest=preflight_prompt_digest,
                            supports_cancellation=True,
                        )
                        if escalation is not None
                        else None
                    ),
                    narrator=(
                        SocialResponseNarratorBinding(
                            model=primary,
                            model_config_digest=t1_config_digest,
                            prompt_digest=social_narrator_prompt_digest,
                        )
                        if social_narrator_prompt_digest is not None
                        else None
                    ),
                )
                if preflight_prompt_digest is not None
                else None
            ),
        )

    return factory
