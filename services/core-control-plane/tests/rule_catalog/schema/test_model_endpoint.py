"""Heterogeneous model endpoint binding contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.rule_catalog.schema.llm_resolver import ResolvedModels
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


def _binding(**changes: object) -> ModelEndpointBinding:
    values: dict[str, object] = {
        "binding_id": "t2-primary-prod",
        "capability": "t2.reasoner.primary",
        "provider_kind": ModelProviderKind.AZURE_OPENAI,
        "route_kind": ModelRouteKind.APIM_GATEWAY,
        "api_style": ModelApiStyle.AZURE_OPENAI,
        "endpoint_ref": "model-gateway-primary",
        "deployment": "t2-primary",
        "api_version": "2024-10-21",
        "auth_kind": ModelAuthKind.ENTRA,
        "auth_audience": "api://fdai-model-gateway",
        "publisher": "OpenAI",
        "family": "gpt-4o",
        "version": "2024-08-06",
        "capacity": ModelEndpointCapacity(unit=ModelCapacityUnit.PTU, value=30),
        "features": ModelEndpointFeatures(
            streaming=True,
            structured_output=True,
            tool_calling=True,
        ),
        "discovery": ModelEndpointDiscovery(
            source=ModelDiscoverySource.APIM_MANAGEMENT,
            resource_ref_digest="a" * 64,
            verified_at=datetime(2026, 7, 17, tzinfo=UTC),
        ),
    }
    values.update(changes)
    return ModelEndpointBinding(**values)  # type: ignore[arg-type]


def _resolved(*bindings: ModelEndpointBinding) -> ResolvedModels:
    return ResolvedModels(
        schema_version="1.0.0",
        region="koreacentral",
        subscription_id="00000000-0000-0000-0000-000000000000",
        deployer_object_id="00000000-0000-0000-0000-000000000001",
        mixed_model_mode="azure-foundry",
        capabilities=(),
        endpoint_bindings=bindings,
    )


def test_resolved_models_endpoint_binding_round_trips_deterministically() -> None:
    original = _resolved(_binding())

    restored = ResolvedModels.from_json(original.to_json())

    assert restored == original
    assert '"endpoint_bindings"' in restored.to_json()
    assert "https://" not in restored.to_json()


def test_resolved_models_without_endpoint_bindings_preserves_v1_shape() -> None:
    text = _resolved().to_json()

    assert "endpoint_bindings" not in text
    assert ResolvedModels.from_json(text).to_json() == text


def test_self_hosted_gpu_binding_supports_apim_openai_v1() -> None:
    binding = _binding(
        provider_kind=ModelProviderKind.SELF_HOSTED,
        api_style=ModelApiStyle.OPENAI_V1,
        capacity=ModelEndpointCapacity(unit=ModelCapacityUnit.GPU, value=2),
        publisher="Qwen",
        family="Qwen2.5-Instruct",
        discovery=ModelEndpointDiscovery(
            source=ModelDiscoverySource.SIGNED_REGISTRATION,
            resource_ref_digest="b" * 64,
            verified_at=datetime(2026, 7, 17, tzinfo=UTC),
        ),
    )

    assert binding.route_kind is ModelRouteKind.APIM_GATEWAY
    assert binding.capacity.unit is ModelCapacityUnit.GPU


@pytest.mark.parametrize(
    "changes",
    (
        {
            "provider_kind": ModelProviderKind.SELF_HOSTED,
            "api_style": ModelApiStyle.AZURE_OPENAI,
            "capacity": ModelEndpointCapacity(unit=ModelCapacityUnit.GPU, value=1),
        },
        {
            "provider_kind": ModelProviderKind.SELF_HOSTED,
            "api_style": ModelApiStyle.OPENAI_V1,
            "capacity": ModelEndpointCapacity(unit=ModelCapacityUnit.PTU, value=1),
        },
        {
            "provider_kind": ModelProviderKind.AZURE_OPENAI,
            "capacity": ModelEndpointCapacity(unit=ModelCapacityUnit.GPU, value=1),
        },
        {"auth_kind": ModelAuthKind.ENTRA, "auth_audience": None},
    ),
)
def test_endpoint_binding_rejects_invalid_provider_protocol_capacity_auth_combinations(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _binding(**changes)


def test_resolved_models_rejects_duplicate_capability_bindings() -> None:
    with pytest.raises(ValueError, match="capabilities MUST be unique"):
        _resolved(_binding(binding_id="one"), _binding(binding_id="two"))
