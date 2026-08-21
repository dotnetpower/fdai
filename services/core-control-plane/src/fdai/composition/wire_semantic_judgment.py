"""Production factory wiring for no-authority semantic judgment."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import httpx
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.semantic_judgment import SemanticJudgmentTier

from fdai.core.conversation.semantic_judgment import (
    SemanticJudgmentBinding,
    SemanticJudgmentBoundary,
)
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.delivery.azure.llm.semantic_judgment import (
    AzureOpenAISemanticJudgmentModel,
    AzureOpenAISemanticJudgmentModelConfig,
)
from fdai.rule_catalog.schema.llm_resolver import ResolvedModels
from fdai.shared.providers.workload_identity import WorkloadIdentity

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
    )
    available_tiers = ["t1"] + (["t2"] if t2_targets else [])
    _LOGGER.info(
        "semantic_judgment_factory_bound",
        extra={"available_tiers": available_tiers},
    )
    prompt_digest = content_digest({"prompt": system_prompt})
    t1_config_digest = content_digest(
        {"targets": [_target_record(target) for target in t1_targets]}
    )
    t2_config_digest = content_digest(
        {"targets": [_target_record(target) for target in t2_targets]}
    )

    def factory(owner_loop: asyncio.AbstractEventLoop) -> SemanticJudgmentBoundary:
        primary = AzureOpenAISemanticJudgmentModel(
            identity=identity,
            http_client=http_client,
            config=AzureOpenAISemanticJudgmentModelConfig(
                candidates=t1_targets,
                system_prompt=system_prompt,
            ),
            owner_loop=owner_loop,
        )
        escalation = (
            AzureOpenAISemanticJudgmentModel(
                identity=identity,
                http_client=http_client,
                config=AzureOpenAISemanticJudgmentModelConfig(
                    candidates=t2_targets,
                    system_prompt=system_prompt,
                ),
                owner_loop=owner_loop,
            )
            if t2_targets
            else None
        )
        return SemanticJudgmentBoundary(
            profile_id="pantheon-conversation",
            profile_version="1.0.0",
            primary=SemanticJudgmentBinding(
                tier=SemanticJudgmentTier.T1,
                model=primary,
                model_config_digest=t1_config_digest,
                prompt_digest=prompt_digest,
            ),
            escalation=(
                SemanticJudgmentBinding(
                    tier=SemanticJudgmentTier.T2,
                    model=escalation,
                    model_config_digest=t2_config_digest,
                    prompt_digest=prompt_digest,
                )
                if escalation is not None
                else None
            ),
        )

    return factory


def _target_record(target: ModelRequestTarget) -> dict[str, object]:
    return {
        "endpoint": target.endpoint,
        "deployment": target.deployment,
        "api_version": target.api_version,
        "api_style": target.api_style.value,
        "route_kind": target.route_kind.value,
        "binding_id": target.binding_id,
    }


__all__ = ["SemanticJudgmentFactory", "build_azure_semantic_judgment_factory"]
