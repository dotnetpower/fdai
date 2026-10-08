"""Pinned composition of the runtime typed instance selection shadow (#2011).

The shadow observer binds only the proposer that protocol
``agreement-gated-pooled-qualification.v1`` qualified: the same resolved model family and version,
the same diagnostic prompt profile and system text, effort, timeout, and output ceiling. Any
mismatch returns a typed reason instead of a weaker binding. The binding grants no answer
authority; it enables shadow evidence only after the operator opts in.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.prompts import PromptAssembler
from fdai.core.prompts.registry import FileSystemPromptRegistry
from fdai.delivery.azure.llm.semantic_planning import (
    AzureOpenAISemanticPlanningModel,
    AzureOpenAISemanticPlanningModelConfig,
)
from fdai.delivery.azure.llm.semantic_planning_config import candidate_proposal_binding
from fdai.delivery.catalog_search.ontology_typed_selection_shadow import TypedSelectionShadowBinding
from fdai.shared.config.models import LlmMode
from fdai.shared.providers.workload_identity import WorkloadIdentity

from ._helpers import Container
from .resolved_models import _capability
from .resolved_models_revision import resolved_models_for_binding
from .semantic_query_model_targets import t2_model_targets

SHADOW_ENABLE_ENV = "FDAI_ONTOLOGY_TYPED_SELECTION_SHADOW"
SHADOW_CONFIG_RELATIVE_PATH = Path("config/ontology-typed-selection-shadow.json")


@dataclass(frozen=True, slots=True)
class TypedSelectionShadowPin:
    """Reviewed qualification identity and data-handling policy from the repository config."""

    model_capability: str
    model_family: str
    model_version: str
    prompt_profile_id: str
    prompt_profile_digest: str
    system_text_sha256: str
    reasoning_effort: str
    timeout_seconds: float
    max_tokens: int
    data_handling_policy_digest: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> TypedSelectionShadowPin:
        if (
            raw.get("schema_version") != "1.0.0"
            or raw.get("runtime_protocol_id") != "typed-selection-runtime-shadow.v1"
            or raw.get("mode") != "shadow"
        ):
            raise ValueError("typed selection shadow config identity is not reviewed")
        qualified = raw["qualification"]
        policy = raw["data_handling"]
        if not isinstance(qualified, Mapping) or not isinstance(policy, Mapping):
            raise ValueError("typed selection shadow config sections are required")
        if policy.get("answer_authority") != "none":
            raise ValueError("typed selection shadow policy cannot grant answer authority")
        return cls(
            model_capability=str(qualified["model_capability"]),
            model_family=str(qualified["model_family"]),
            model_version=str(qualified["model_version"]),
            prompt_profile_id=str(qualified["prompt_profile_id"]),
            prompt_profile_digest=str(qualified["prompt_profile_digest"]),
            system_text_sha256=str(qualified["system_text_sha256"]),
            reasoning_effort=str(qualified["reasoning_effort"]),
            timeout_seconds=float(qualified["timeout_seconds"]),
            max_tokens=int(qualified["max_tokens"]),
            data_handling_policy_digest=content_digest(dict(policy)),
        )

    @classmethod
    def load(cls, path: Path) -> TypedSelectionShadowPin:
        return cls.from_mapping(json.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True, slots=True)
class TypedSelectionShadowComposition:
    binding: TypedSelectionShadowBinding | None
    reason: str


def compose_typed_selection_shadow(
    *,
    container: Container,
    environment: Mapping[str, str],
    identity: WorkloadIdentity | None,
    http_client: httpx.AsyncClient | None,
    endpoint: str | None,
    endpoint_resolver: Callable[[str], str] | None,
    catalog_root: Path,
    config_path: Path,
    owner_loop: asyncio.AbstractEventLoop,
) -> TypedSelectionShadowComposition:
    """Bind the qualified proposer only for an explicit opt-in; otherwise return a reason."""

    if environment.get(SHADOW_ENABLE_ENV, "").strip().lower() != "enabled":
        return TypedSelectionShadowComposition(None, "typed_selection_shadow_disabled")
    if container.config.llm.mode != LlmMode.AZURE:
        return TypedSelectionShadowComposition(None, "typed_selection_shadow_llm_unavailable")
    if identity is None or http_client is None:
        return TypedSelectionShadowComposition(None, "typed_selection_shadow_transport_unavailable")
    try:
        pin = TypedSelectionShadowPin.load(config_path)
    except (OSError, ValueError, KeyError, TypeError):
        return TypedSelectionShadowComposition(None, "typed_selection_shadow_policy_unavailable")
    try:
        resolved = resolved_models_for_binding(container)
    except Exception:  # noqa: BLE001 - every resolution failure is one typed reason
        return TypedSelectionShadowComposition(None, "typed_selection_shadow_models_unavailable")
    capability = _capability(
        resolved, pin.model_capability, held_capabilities=container.held_model_capabilities
    )
    targets = t2_model_targets(
        resolved,
        endpoint=endpoint,
        endpoint_resolver=endpoint_resolver,
        held_capabilities=container.held_model_capabilities,
    )
    if capability is None or not targets:
        return TypedSelectionShadowComposition(None, "typed_selection_shadow_target_unavailable")
    if not capability_matches_pin(pin, capability):
        return TypedSelectionShadowComposition(None, "typed_selection_shadow_model_not_qualified")
    return bind_qualified_proposer(
        pin,
        target=targets[0],
        identity=identity,
        http_client=http_client,
        catalog_root=catalog_root,
        owner_loop=owner_loop,
    )


def capability_matches_pin(pin: TypedSelectionShadowPin, capability: object) -> bool:
    """Return whether a resolved model capability is the exact qualified family and version."""
    return (
        getattr(capability, "family", None) == pin.model_family
        and getattr(capability, "version", None) == pin.model_version
    )


def bind_qualified_proposer(
    pin: TypedSelectionShadowPin,
    *,
    target: Any,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    catalog_root: Path,
    owner_loop: asyncio.AbstractEventLoop,
) -> TypedSelectionShadowComposition:
    prompts = FileSystemPromptRegistry(catalog_root)
    selection = prompts.resolve("semantic.query.plan", profile_id=pin.prompt_profile_id)
    plan = PromptAssembler(selection).complete
    frame = PromptAssembler(prompts.resolve("semantic.query.frame")).complete
    config = AzureOpenAISemanticPlanningModelConfig(
        candidates=(target,),
        frame_system_prompt=frame.system_text,
        plan_system_prompt=plan.system_text,
        plan_prompt_manifest=plan.replay_manifest(),
        timeout_seconds=pin.timeout_seconds,
        max_tokens=pin.max_tokens,
        reasoning_effort=pin.reasoning_effort,
    )
    binding = candidate_proposal_binding(config)
    manifest = binding.prompt_manifest
    profile = selection.profile
    if (
        profile is None
        or profile.reasoning_effort != pin.reasoning_effort
        or profile.reserved_output_tokens != pin.max_tokens
        or manifest.profile_id != pin.prompt_profile_id
        or manifest.profile_digest != pin.prompt_profile_digest
        or manifest.system_text_sha256 != pin.system_text_sha256
    ):
        return TypedSelectionShadowComposition(None, "typed_selection_shadow_prompt_not_qualified")
    proposer = AzureOpenAISemanticPlanningModel(
        identity=identity, http_client=http_client, config=config, owner_loop=owner_loop
    )
    return TypedSelectionShadowComposition(
        TypedSelectionShadowBinding(
            proposer=proposer,
            data_handling_policy_digest=pin.data_handling_policy_digest,
            expected_binding=binding,
        ),
        "typed_selection_shadow_bound",
    )


__all__ = [
    "SHADOW_CONFIG_RELATIVE_PATH",
    "SHADOW_ENABLE_ENV",
    "bind_qualified_proposer",
    "capability_matches_pin",
    "TypedSelectionShadowComposition",
    "TypedSelectionShadowPin",
    "compose_typed_selection_shadow",
]
