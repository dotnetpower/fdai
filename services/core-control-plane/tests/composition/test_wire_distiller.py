"""Focused composition tests for the Azure ontology council distiller."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fdai.composition import (
    LlmBindingsUnavailableError,
    bind_azure_ontology_distiller,
    default_container,
)
from fdai.composition.wire_distiller import (
    OntologyCouncilBindingState,
    ontology_council_binding_state,
)
from fdai.core.metering.sink import InMemoryMeteringSink
from fdai.rule_catalog.pipeline.distill.ontology_council import OntologyCouncilDistiller
from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    ResolvedCapability,
    ResolvedModels,
)
from fdai.rule_catalog.schema.model_endpoint import (
    ModelApiStyle,
    ModelAuthKind,
    ModelCapacityUnit,
    ModelDiscoverySource,
    ModelEndpointBinding,
    ModelEndpointCapacity,
    ModelEndpointDiscovery,
    ModelEndpointFeatures,
    ModelProviderKind,
    ModelRouteKind,
)
from fdai.shared.config import AppConfig
from fdai.shared.providers.distiller import AbstainingDistiller
from fdai.shared.providers.workload_identity import IdentityToken

_CAPABILITIES = (
    ("t2.ontology.council.alpha", "gpt-5.6-sol", 50_000),
    ("t2.ontology.council.beta", "gpt-5.5", 50_000),
    ("t2.ontology.council.gamma", "gpt-5.4", 100_000),
)


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
            audience=audience,
        )


def _capability(name: str, family: str, capacity: int) -> ResolvedCapability:
    return ResolvedCapability(
        name=name,
        status=CapabilityStatus.RESOLVED,
        publisher="OpenAI",
        family=family,
        sku="GlobalStandard",
        capacity_tpm=capacity,
        invocation="on_novel_case",
    )


def _binding(
    name: str,
    family: str,
    capacity: int,
    *,
    route_kind: ModelRouteKind = ModelRouteKind.DIRECT,
) -> ModelEndpointBinding:
    return ModelEndpointBinding(
        binding_id=name.replace(".", "-") + "-binding",
        capability=name,
        provider_kind=ModelProviderKind.AZURE_OPENAI,
        route_kind=route_kind,
        api_style=ModelApiStyle.AZURE_OPENAI,
        endpoint_ref=name.replace(".", "-"),
        deployment=name.replace(".", "-"),
        api_version="2024-12-01-preview",
        auth_kind=ModelAuthKind.ENTRA,
        auth_audience="https://cognitiveservices.azure.com/.default",
        publisher="OpenAI",
        family=family,
        version="2026-08-01",
        capacity=ModelEndpointCapacity(unit=ModelCapacityUnit.TPM, value=capacity),
        features=ModelEndpointFeatures(structured_output=True),
        discovery=ModelEndpointDiscovery(
            source=ModelDiscoverySource.AZURE_MANAGEMENT,
            resource_ref_digest="a" * 64,
            verified_at=datetime(2026, 8, 3, tzinfo=UTC),
        ),
    )


def _resolved(
    *,
    capabilities: tuple[ResolvedCapability, ...] | None = None,
    bindings: tuple[ModelEndpointBinding, ...] | None = None,
) -> ResolvedModels:
    return ResolvedModels(
        schema_version="1.0.0",
        region="koreacentral",
        subscription_id="00000000-0000-0000-0000-000000000000",
        deployer_object_id="00000000-0000-0000-0000-000000000000",
        mixed_model_mode="azure-foundry",
        capabilities=(
            capabilities
            if capabilities is not None
            else tuple(_capability(*values) for values in _CAPABILITIES)
        ),
        endpoint_bindings=(
            bindings
            if bindings is not None
            else tuple(_binding(*values) for values in _CAPABILITIES)
        ),
    )


def _container(resolved: ResolvedModels):  # type: ignore[no-untyped-def]
    config = AppConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "azure": {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "region": "koreacentral",
            },
            "kafka": {
                "bootstrap_servers": "events.example.com:9093",
                "topic_events": "fdai.events",
            },
            "postgres": {"host": "postgres.example.com", "database": "fdai"},
            "runtime": {"env": "dev"},
            "llm": {"mode": "azure", "resolved_models_path": resolved.to_json()},
        }
    )
    return default_container(config)


def _bind(resolved: ResolvedModels, **changes: Any):  # type: ignore[no-untyped-def]
    values: dict[str, Any] = {
        "container": _container(resolved),
        "identity": _Identity(),
        "http_client": httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200))
        ),
        "endpoint": "https://legacy.example.com",
        "system_prompt": "Return one strict ontology council vote.",
        "prompt_digest": "b" * 64,
        "schema_digest": "c" * 64,
        "endpoint_resolver": lambda endpoint_ref: f"https://{endpoint_ref}.example.com",
    }
    values.update(changes)
    return bind_azure_ontology_distiller(**values)


def test_zero_council_records_preserve_existing_abstaining_distiller() -> None:
    resolved = _resolved(capabilities=(), bindings=())
    container = _container(resolved)

    result = _bind(resolved, container=container, endpoint_resolver=None)

    assert result is container
    assert isinstance(result.distiller, AbstainingDistiller)
    assert ontology_council_binding_state(resolved) is OntologyCouncilBindingState.ABSENT


def test_complete_bindings_attach_exact_versioned_metered_council() -> None:
    resolved = _resolved()
    metering = InMemoryMeteringSink()

    result = _bind(resolved, metering_sink=metering)

    assert isinstance(result.distiller, OntologyCouncilDistiller)
    assert ontology_council_binding_state(resolved) is OntologyCouncilBindingState.COMPLETE
    models = result.distiller._models
    assert {model.identity.family for model in models} == {
        "gpt-5.6-sol",
        "gpt-5.5",
        "gpt-5.4",
    }
    assert {model.identity.version for model in models} == {"2026-08-01"}
    assert {model.identity.fault_domain for model in models} == {"a" * 64}
    assert {model._config.api_version for model in models} == {"2024-12-01-preview"}
    assert {model._config.route_kind for model in models} == {ModelRouteKind.DIRECT}
    assert {model._metering._capability_id for model in models} == {
        name for name, _family, _capacity in _CAPABILITIES
    }
    assert {model._metering._model_key for model in models} == {
        family for _name, family, _capacity in _CAPABILITIES
    }


@pytest.mark.parametrize("missing", ["capability", "binding"])
def test_partial_council_configuration_fails_closed(missing: str) -> None:
    capabilities = tuple(_capability(*values) for values in _CAPABILITIES)
    bindings = tuple(_binding(*values) for values in _CAPABILITIES)
    resolved = _resolved(
        capabilities=capabilities[:-1] if missing == "capability" else capabilities,
        bindings=bindings[:-1] if missing == "binding" else bindings,
    )

    with pytest.raises(LlmBindingsUnavailableError, match="requires all three"):
        _bind(resolved)


def test_hil_only_council_capability_fails_closed() -> None:
    capabilities = list(_resolved().capabilities)
    capabilities[-1] = replace(capabilities[-1], status=CapabilityStatus.HIL_ONLY)

    with pytest.raises(LlmBindingsUnavailableError, match="requires all three"):
        _bind(_resolved(capabilities=tuple(capabilities)))


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"version": None}, "exact version"),
        ({"features": ModelEndpointFeatures()}, "structured output"),
        (
            {"auth_kind": ModelAuthKind.API_KEY_REF, "auth_audience": None},
            "Entra auth",
        ),
        ({"family": "gpt-5.6-sol"}, "distinct model families"),
    ),
)
def test_invalid_endpoint_binding_fails_closed(
    change: dict[str, object],
    message: str,
) -> None:
    bindings = list(_resolved().endpoint_bindings)
    bindings[1] = replace(bindings[1], **change)
    capabilities = list(_resolved().capabilities)
    if change.get("family") is not None:
        capabilities[1] = replace(capabilities[1], family=str(change["family"]))

    with pytest.raises(LlmBindingsUnavailableError, match=message):
        _bind(_resolved(capabilities=tuple(capabilities), bindings=tuple(bindings)))


def test_family_mismatch_fails_closed() -> None:
    bindings = list(_resolved().endpoint_bindings)
    bindings[0] = replace(bindings[0], family="gpt-mismatch")

    with pytest.raises(LlmBindingsUnavailableError, match="does not match"):
        _bind(_resolved(bindings=tuple(bindings)))


def test_mixed_publishers_fail_closed() -> None:
    capabilities = list(_resolved().capabilities)
    bindings = list(_resolved().endpoint_bindings)
    capabilities[1] = replace(capabilities[1], publisher="OtherPublisher")
    bindings[1] = replace(bindings[1], publisher="OtherPublisher")

    with pytest.raises(LlmBindingsUnavailableError, match="single publisher"):
        _bind(
            _resolved(
                capabilities=tuple(capabilities),
                bindings=tuple(bindings),
            )
        )


def test_missing_endpoint_resolver_fails_closed() -> None:
    with pytest.raises(LlmBindingsUnavailableError, match="endpoint_ref resolver"):
        _bind(_resolved(), endpoint_resolver=None)


def test_apim_without_health_sink_fails_closed() -> None:
    bindings = tuple(
        replace(binding, route_kind=ModelRouteKind.APIM_GATEWAY)
        for binding in _resolved().endpoint_bindings
    )

    with pytest.raises(LlmBindingsUnavailableError, match="model health"):
        _bind(_resolved(bindings=bindings))
