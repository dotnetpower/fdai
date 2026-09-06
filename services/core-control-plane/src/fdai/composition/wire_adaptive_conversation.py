"""Build adaptive presentation dependencies from verified server registries."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

import httpx

from fdai.agents import PANTHEON_SPECS, AgentSpec
from fdai.core.conversation.adaptive_models import DEFAULT_ADAPTIVE_POLICY
from fdai.core.conversation.adaptive_prompt import (
    ADAPTIVE_STAGES,
    AdaptiveModel,
    ConversationProfile,
    VerifiedConversationRelationship,
    compose_adaptive_prompt,
)
from fdai.core.conversation.adaptive_service import AdaptiveConversationService
from fdai.core.prompts import FileSystemPromptRegistry, PromptComposer, PromptLayer
from fdai.delivery.azure.llm.adaptive_answer import (
    AzureOpenAIAdaptiveModel,
)
from fdai.rule_catalog.schema.llm_resolver import ResolvedModels
from fdai.shared.providers.workload_identity import WorkloadIdentity

from .adaptive_model_targets import resolved_model_config as _resolved_model_config

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AdaptiveConversationDependencies:
    """Immutable model and catalog prompt snapshot; grants no runtime authority."""

    model: AdaptiveModel
    profile: ConversationProfile
    stage_prompts: Mapping[str, str]
    prompt_digests: Mapping[str, str]
    layer_ids: Mapping[str, tuple[str, ...]]
    profile_resolver: Callable[[str, str, Mapping[str, object] | None], ConversationProfile]
    refinement_available: bool


def build_adaptive_conversation_profile(
    *,
    agent: str,
    locale: str = "en",
    relationship: VerifiedConversationRelationship | None = None,
    pantheon_specs: Sequence[AgentSpec] = PANTHEON_SPECS,
) -> ConversationProfile:
    """Select a fixed agent's server-owned directive, never accept caller prose.

    ``pantheon_specs`` is a server composition dependency, not request data.
    Relationship provenance and its current revision must already have been
    checked against authenticated server context for this turn.
    """

    canonical = next((spec for spec in PANTHEON_SPECS if spec.name == agent), None)
    descriptors = [spec for spec in pantheon_specs if spec.name == agent]
    if canonical is None or len(descriptors) != 1:
        raise ValueError("adaptive conversation requires one fixed Pantheon descriptor")
    descriptor = descriptors[0]
    if descriptor.conversation.role_directive != canonical.conversation.role_directive:
        raise ValueError("adaptive conversation cannot override a fixed Pantheon role")
    return ConversationProfile(
        agent=descriptor.name,
        role_directive=descriptor.conversation.role_directive,
        locale=locale,
        relationship=relationship,
    )


def resolve_adaptive_conversation_profile(
    agent: str,
    locale: str,
    server_context: Mapping[str, object] | None,
    *,
    pantheon_specs: Sequence[AgentSpec] = PANTHEON_SPECS,
    now: datetime | None = None,
) -> ConversationProfile:
    """Resolve a role without an ontology store or accepting UI relationship claims.

    Only an actual ``VerifiedConversationRelationship`` under the server-only
    ``verified_relationship`` key may affect presentation. Raw dictionaries,
    strings, and booleans are ignored, including request-shaped imitations of a
    verification result. The server must recheck its current revision per turn.
    No other context field can override the explicitly selected agent or locale.
    """

    relationship = server_context.get("verified_relationship") if server_context else None
    return build_adaptive_conversation_profile(
        agent=agent,
        locale=locale,
        relationship=(
            relationship
            if isinstance(relationship, VerifiedConversationRelationship)
            and relationship.is_current_for(agent, now if now is not None else datetime.now(UTC))
            else None
        ),
        pantheon_specs=pantheon_specs,
    )


def build_adaptive_conversation_service(
    *,
    resolved: ResolvedModels,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    endpoint: str | None,
    endpoint_resolver: Callable[[str], str] | None,
    catalog_root: Path,
    held_capabilities: frozenset[str] = frozenset(),
    model_factory: Callable[[], AdaptiveModel | None] | None = None,
) -> AdaptiveConversationService | None:
    """Synchronously bind the adaptive service without a loop or provider calls.

    Snapshot exactly the common base and one stage pack through the validated
    registry. Selecting these specific shadow packs does not activate any other
    shadow prompt or grant operational authority. Per-turn composition adds one
    fixed Pantheon role and verified profile facts, never mutable runtime prose.
    Missing configuration yields ``None`` with a content-free diagnostic.
    """

    try:
        config = _resolved_model_config(
            resolved,
            endpoint=endpoint,
            endpoint_resolver=endpoint_resolver,
            held_capabilities=held_capabilities,
            timeout_seconds=DEFAULT_ADAPTIVE_POLICY.per_stage_seconds,
            max_tokens=DEFAULT_ADAPTIVE_POLICY.reserved_output_tokens,
        )
        if config is None:
            _unavailable("model_binding_unavailable")
            return None
        registry = FileSystemPromptRegistry(catalog_root)
        profiles = tuple(
            build_adaptive_conversation_profile(agent=spec.name) for spec in PANTHEON_SPECS
        )
        prompts: dict[str, str] = {}
        for stage in ADAPTIVE_STAGES:
            capability = f"conversation.adaptive.{stage}"
            base = registry.get_base(capability)
            packs = registry.get_packs(capability)
            layers = (base, *packs)
            if tuple((layer.id, layer.layer) for layer in layers) != (
                ("adaptive-common", PromptLayer.BASE),
                (f"adaptive-{stage}", PromptLayer.PACK),
            ):
                _unavailable("prompt_layers_unavailable")
                return None
            text = "\n\n".join(layer.body for layer in layers)
            for profile in profiles:
                compose_adaptive_prompt(profile, stage, text)
            prompts[stage] = text
        service = AdaptiveConversationService(
            model=AzureOpenAIAdaptiveModel(
                identity=identity, http_client=http_client, config=config
            ),
            profile_resolver=resolve_adaptive_conversation_profile,
            model_factory=model_factory,
            prompts=MappingProxyType(prompts),
            policy=replace(
                DEFAULT_ADAPTIVE_POLICY,
                refinement_enabled=(
                    DEFAULT_ADAPTIVE_POLICY.refinement_enabled and config.escalation is not None
                ),
            ),
        )
        _LOGGER.info(
            "adaptive_conversation_configured",
            extra={"refinement_available": config.escalation is not None},
        )
        return service
    except (LookupError, OSError, ValueError):
        _unavailable("configuration_unavailable")
        return None


async def build_adaptive_conversation_dependencies(
    *,
    resolved: ResolvedModels,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    prompt_composer: PromptComposer,
    agent: str,
    endpoint: str | None = None,
    endpoint_resolver: Callable[[str], str] | None = None,
    held_capabilities: frozenset[str] = frozenset(),
    locale: str = "en",
    relationship: VerifiedConversationRelationship | None = None,
    pantheon_specs: Sequence[AgentSpec] = PANTHEON_SPECS,
    primary_capability: str = "t1.judge",
    reviewer_capability: str | None = None,
    escalation_capability: str = "t2.reasoner.primary",
    timeout_seconds: float = 20.0,
    max_tokens: int = 4_096,
) -> AdaptiveConversationDependencies | None:
    """Bind independent configured models and common-plus-stage prompt layers.

    No network or identity calls occur at composition. Missing/held models,
    unknown model provenance, non-independent review, missing stage packs, or
    dynamic system layers yield ``None``. An unavailable T2 target disables
    explicit refinement, not ordinary T1 generation and independent review.

    The composer must explicitly enable ``ADAPTIVE_STAGE_PACK_IDS`` while their
    catalog mode is shadow. It is called without operator scope or runtime skill
    disclosure; only the exact common base and selected stage pack are accepted.
    ``stage_prompts`` contain catalog text, not the profile: call
    ``compose_adaptive_prompt(profile, stage, stage_prompts[stage])`` per turn.
    Pass the returned ``profile_resolver`` directly to the conversation service,
    and intersect its refinement policy with ``refinement_available``.
    The service must reserve at least ``max_tokens`` output tokens per call and
    retain its separate total-turn, five-call, and two-read limits.
    """

    fixed_specs = tuple(pantheon_specs)

    def profile_resolver(
        agent_name: str, operator_locale: str, server_context: Mapping[str, object] | None
    ) -> ConversationProfile:
        return resolve_adaptive_conversation_profile(
            agent_name, operator_locale, server_context, pantheon_specs=fixed_specs
        )

    profile = build_adaptive_conversation_profile(
        agent=agent,
        locale=locale,
        relationship=relationship,
        pantheon_specs=fixed_specs,
    )

    try:
        config = _resolved_model_config(
            resolved,
            endpoint=endpoint,
            endpoint_resolver=endpoint_resolver,
            held_capabilities=held_capabilities,
            primary_capability=primary_capability,
            reviewer_capability=reviewer_capability,
            escalation_capability=escalation_capability,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
        )
        if config is None:
            _unavailable("model_binding_unavailable")
            return None
        prompts: dict[str, str] = {}
        digests: dict[str, str] = {}
        layer_ids: dict[str, tuple[str, ...]] = {}
        for stage in ADAPTIVE_STAGES:
            composed = await prompt_composer.compose(capability_id=f"conversation.adaptive.{stage}")
            layers = tuple((layer.id, layer.layer) for layer in composed.layer_manifest)
            if layers != (
                ("adaptive-common", PromptLayer.BASE),
                (f"adaptive-{stage}", PromptLayer.PACK),
            ):
                _unavailable("prompt_layers_unavailable")
                return None
            compose_adaptive_prompt(profile, stage, composed.system_text)
            prompts[stage] = composed.system_text
            digests[stage] = hashlib.sha256(composed.system_text.encode("utf-8")).hexdigest()
            layer_ids[stage] = tuple(
                f"{layer.id}.v{layer.version}" for layer in composed.layer_manifest
            )
    except (LookupError, ValueError):
        _unavailable("configuration_unavailable")
        return None
    return AdaptiveConversationDependencies(
        model=AzureOpenAIAdaptiveModel(identity=identity, http_client=http_client, config=config),
        profile=profile,
        stage_prompts=MappingProxyType(prompts),
        prompt_digests=MappingProxyType(digests),
        layer_ids=MappingProxyType(layer_ids),
        profile_resolver=profile_resolver,
        refinement_available=config.escalation is not None,
    )


def _unavailable(reason: str) -> None:
    _LOGGER.warning("adaptive_conversation_unavailable", extra={"reason": reason})


__all__ = [
    "AdaptiveConversationDependencies",
    "build_adaptive_conversation_dependencies",
    "build_adaptive_conversation_profile",
    "build_adaptive_conversation_service",
    "resolve_adaptive_conversation_profile",
]
