"""Azure ontology council distiller composition binding."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, cast

import httpx

from ..core.metering.emitter import MeteringEmitter
from ..core.metering.pricing import PricingTable
from ..core.metering.sink import MeteringSink
from ..rule_catalog.pipeline.distill.ontology_council import (
    OntologyCouncilDistiller,
    OntologyCouncilPolicy,
)
from ..rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    ResolvedCapability,
    ResolvedModels,
)
from ..rule_catalog.schema.model_endpoint import (
    ModelAuthKind,
    ModelEndpointBinding,
    ModelRouteKind,
)
from ..shared.config.models import LlmMode
from ..shared.providers.distiller import Distiller
from ..shared.providers.ontology_council import CouncilModelIdentity, OntologyCouncilModel
from ..shared.providers.workload_identity import WorkloadIdentity
from ._helpers import Container, LlmBindingsUnavailableError, _load_resolved_models

ONTOLOGY_COUNCIL_CAPABILITIES = (
    "t2.ontology.council.alpha",
    "t2.ontology.council.beta",
    "t2.ontology.council.gamma",
)
_COUNCIL_CAPABILITY_SET = frozenset(ONTOLOGY_COUNCIL_CAPABILITIES)
_POLICY_ID = "t2.ontology.council"
_POLICY_VERSION = "1"


class OntologyCouncilBindingState(StrEnum):
    ABSENT = "absent"
    COMPLETE = "complete"
    PARTIAL = "partial"


class _OntologyDistillerOverrides(Protocol):
    @property
    def endpoint(self) -> str: ...

    @property
    def catalog_root(self) -> Path: ...

    @property
    def model_endpoint_resolver(self) -> Callable[[str], str] | None: ...

    @property
    def metering_sink(self) -> MeteringSink | None: ...

    @property
    def model_health_sink(self) -> Any | None: ...


def ontology_council_binding_state(resolved: ResolvedModels) -> OntologyCouncilBindingState:
    """Classify council records without inspecting unrelated model capabilities."""
    capabilities = tuple(
        capability
        for capability in resolved.capabilities
        if capability.name in _COUNCIL_CAPABILITY_SET
    )
    bindings = tuple(
        binding
        for binding in resolved.endpoint_bindings
        if binding.capability in _COUNCIL_CAPABILITY_SET
    )
    if not capabilities and not bindings:
        return OntologyCouncilBindingState.ABSENT
    capability_names = {capability.name for capability in capabilities}
    binding_capabilities = {binding.capability for binding in bindings}
    if (
        len(capabilities) == 3
        and len(bindings) == 3
        and capability_names == _COUNCIL_CAPABILITY_SET
        and binding_capabilities == _COUNCIL_CAPABILITY_SET
        and all(capability.status != CapabilityStatus.HIL_ONLY for capability in capabilities)
    ):
        return OntologyCouncilBindingState.COMPLETE
    return OntologyCouncilBindingState.PARTIAL


async def bind_azure_ontology_distiller_from_catalog(
    container: Container,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    composer: Any,
    overrides: _OntologyDistillerOverrides,
    pricing: PricingTable | None,
) -> Container:
    """Compose the shared council prompt and bind its exact endpoint set."""
    resolved_path = container.config.llm.resolved_models_path
    if resolved_path is None:
        raise LlmBindingsUnavailableError("Azure LLM wiring requires resolved model bindings")
    state = ontology_council_binding_state(_load_resolved_models(resolved_path))
    system_prompt = ""
    prompt_digest = ""
    schema_digest = ""
    if state != OntologyCouncilBindingState.ABSENT:
        try:
            prompts = tuple(
                [
                    await composer.compose(capability_id=capability_id)
                    for capability_id in ONTOLOGY_COUNCIL_CAPABILITIES
                ]
            )
        except LookupError:
            raise LlmBindingsUnavailableError(
                "configured ontology council requires its catalog prompt"
            ) from None
        replay_manifests = tuple(prompt.replay_manifest() for prompt in prompts)
        if len({prompt.system_text for prompt in prompts}) != 1 or len(set(replay_manifests)) != 1:
            raise LlmBindingsUnavailableError(
                "ontology council roles require identical prompt text and replay layers"
            )
        system_prompt = prompts[0].system_text
        prompt_digest = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
        schema_path = (
            overrides.catalog_root / "prompts" / "schema" / "ontology-council-vote.schema.json"
        )
        try:
            schema_digest = hashlib.sha256(schema_path.read_bytes()).hexdigest()
        except OSError:
            raise LlmBindingsUnavailableError(
                "configured ontology council requires its response schema"
            ) from None
    return bind_azure_ontology_distiller(
        container,
        identity=identity,
        http_client=http_client,
        endpoint=overrides.endpoint,
        system_prompt=system_prompt,
        prompt_digest=prompt_digest,
        schema_digest=schema_digest,
        endpoint_resolver=overrides.model_endpoint_resolver,
        metering_sink=overrides.metering_sink,
        pricing=pricing,
        model_health_sink=overrides.model_health_sink,
    )


def bind_azure_ontology_distiller(
    container: Container,
    *,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    endpoint: str,
    system_prompt: str,
    prompt_digest: str,
    schema_digest: str,
    metering_sink: MeteringSink | None = None,
    pricing: PricingTable | None = None,
    model_health_sink: Any | None = None,
    endpoint_resolver: Callable[[str], str] | None = None,
) -> Container:
    """Bind the review-only three-family ontology extraction council."""
    if container.config.llm.mode != LlmMode.AZURE:
        raise ValueError("bind_azure_ontology_distiller requires llm.mode='azure'")
    if container.config.llm.resolved_models_path is None:
        raise ValueError("bind_azure_ontology_distiller requires llm.resolved_models_path")
    if not endpoint:
        raise ValueError("bind_azure_ontology_distiller requires a non-empty endpoint")
    resolved = _load_resolved_models(container.config.llm.resolved_models_path)
    state = ontology_council_binding_state(resolved)
    if state == OntologyCouncilBindingState.ABSENT:
        return container
    if state != OntologyCouncilBindingState.COMPLETE:
        raise LlmBindingsUnavailableError(
            "ontology council requires all three bindable capabilities and endpoint bindings"
        )
    if not system_prompt.strip():
        raise ValueError("bind_azure_ontology_distiller requires a non-empty system_prompt")
    if endpoint_resolver is None:
        raise LlmBindingsUnavailableError(
            "ontology council endpoint bindings require an endpoint_ref resolver"
        )

    capabilities = _council_capabilities(resolved)
    bindings = _council_bindings(resolved)
    if (
        any(binding.route_kind is ModelRouteKind.APIM_GATEWAY for binding in bindings.values())
        and model_health_sink is None
    ):
        raise LlmBindingsUnavailableError(
            "APIM ontology council endpoint bindings require a model health transition sink"
        )

    models: list[OntologyCouncilModel] = []
    family_keys: set[tuple[str, str]] = set()
    for capability_id in ONTOLOGY_COUNCIL_CAPABILITIES:
        capability = capabilities[capability_id]
        binding = bindings[capability_id]
        _validate_binding(capability, binding)
        family_key = (binding.publisher, binding.family)
        if family_key in family_keys:
            raise LlmBindingsUnavailableError(
                "ontology council endpoint bindings require three distinct publisher/family pairs"
            )
        family_keys.add(family_key)
        target = _binding_target(binding, endpoint_resolver)
        model_identity = CouncilModelIdentity(
            publisher=binding.publisher,
            family=binding.family,
            version=cast(str, binding.version),
            deployment=binding.deployment,
            binding=binding.binding_id,
            fault_domain=binding.discovery.resource_ref_digest,
        )
        from ..delivery.azure.llm.ontology_council import (
            AzureOpenAIOntologyCouncilModel,
            AzureOpenAIOntologyCouncilModelConfig,
        )

        models.append(
            cast(
                OntologyCouncilModel,
                AzureOpenAIOntologyCouncilModel(
                    identity=identity,
                    http_client=http_client,
                    config=AzureOpenAIOntologyCouncilModelConfig(
                        **target,
                        system_prompt=system_prompt,
                        model_identity=model_identity,
                        capability_id=capability_id,
                    ),
                    metering=_metering_for(
                        capability_id,
                        capability,
                        metering_sink=metering_sink,
                        pricing=pricing,
                    ),
                    gateway_route_sink=model_health_sink,
                ),
            )
        )

    distiller = OntologyCouncilDistiller(
        models=cast(
            tuple[OntologyCouncilModel, OntologyCouncilModel, OntologyCouncilModel],
            tuple(models),
        ),
        policy=OntologyCouncilPolicy(
            policy_id=_POLICY_ID,
            version=_POLICY_VERSION,
            prompt_digest=prompt_digest,
            schema_digest=schema_digest,
        ),
    )
    return replace(container, distiller=cast(Distiller, distiller))


def _council_capabilities(resolved: ResolvedModels) -> dict[str, ResolvedCapability]:
    return {
        capability.name: capability
        for capability in resolved.capabilities
        if capability.name in _COUNCIL_CAPABILITY_SET
    }


def _council_bindings(resolved: ResolvedModels) -> dict[str, ModelEndpointBinding]:
    return {
        binding.capability: binding
        for binding in resolved.endpoint_bindings
        if binding.capability in _COUNCIL_CAPABILITY_SET
    }


def _validate_binding(
    capability: ResolvedCapability,
    binding: ModelEndpointBinding,
) -> None:
    if capability.publisher is None or capability.family is None:
        raise LlmBindingsUnavailableError(
            f"ontology council capability {capability.name!r} lacks resolved model identity"
        )
    if (binding.publisher, binding.family) != (capability.publisher, capability.family):
        raise LlmBindingsUnavailableError(
            f"ontology council endpoint binding {binding.binding_id!r} does not match its "
            "resolved publisher/family"
        )
    if binding.version is None:
        raise LlmBindingsUnavailableError(
            f"ontology council endpoint binding {binding.binding_id!r} requires an exact version"
        )
    if binding.auth_kind is not ModelAuthKind.ENTRA or binding.auth_audience is None:
        raise LlmBindingsUnavailableError(
            f"ontology council endpoint binding {binding.binding_id!r} requires Entra auth"
        )
    if not binding.features.structured_output:
        raise LlmBindingsUnavailableError(
            f"ontology council endpoint binding {binding.binding_id!r} requires structured output"
        )


def _binding_target(
    binding: ModelEndpointBinding,
    endpoint_resolver: Callable[[str], str],
) -> dict[str, Any]:
    endpoint = endpoint_resolver(binding.endpoint_ref)
    if not endpoint:
        raise LlmBindingsUnavailableError(
            f"ontology council endpoint binding {binding.binding_id!r} resolved empty"
        )
    return {
        "endpoint": endpoint,
        "deployment": binding.deployment,
        "api_version": binding.api_version or "2024-10-21",
        "api_style": binding.api_style,
        "auth_audience": cast(str, binding.auth_audience),
        "route_kind": binding.route_kind,
        "binding_id": binding.binding_id,
    }


def _metering_for(
    capability_id: str,
    capability: ResolvedCapability,
    *,
    metering_sink: MeteringSink | None,
    pricing: PricingTable | None,
) -> MeteringEmitter | None:
    if metering_sink is None:
        return None
    return MeteringEmitter(
        sink=metering_sink,
        capability_id=capability_id,
        model_key=cast(str, capability.family),
        tier="T2",
        pricing=pricing,
    )


__all__ = [
    "ONTOLOGY_COUNCIL_CAPABILITIES",
    "OntologyCouncilBindingState",
    "bind_azure_ontology_distiller",
    "ontology_council_binding_state",
]
