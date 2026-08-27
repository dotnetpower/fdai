"""Protected exact-capability deployment gate tests."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest
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

_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "deployment"
    / "azure"
    / "require_resolved_capability.py"
)


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("focused_require_capability", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _resolved(
    *,
    status: CapabilityStatus = CapabilityStatus.RESOLVED,
    family: str = "Mistral-Large-3",
    endpoint_ref: str = "azure-foundry:aif-fdai-models-staging-krc",
) -> ResolvedModels:
    return ResolvedModels(
        schema_version="1.0.0",
        region="koreacentral",
        subscription_id="00000000-0000-0000-0000-000000000000",
        deployer_object_id="00000000-0000-0000-0000-000000000001",
        mixed_model_mode="azure-foundry",
        capabilities=(
            ResolvedCapability(
                name="t2.reasoner.secondary",
                status=status,
                publisher="MistralAI",
                family=family,
                version="1",
                sku="GlobalStandard",
                capacity_tpm=1_000,
                invocation="always",
            ),
        ),
        endpoint_bindings=(
            ModelEndpointBinding(
                binding_id="foundry-direct:t2.reasoner.secondary",
                capability="t2.reasoner.secondary",
                provider_kind=ModelProviderKind.AZURE_FOUNDRY,
                route_kind=ModelRouteKind.DIRECT,
                api_style=ModelApiStyle.OPENAI_V1,
                endpoint_ref=endpoint_ref,
                deployment="t2.reasoner.secondary",
                auth_kind=ModelAuthKind.ENTRA,
                auth_audience="https://cognitiveservices.azure.com/.default",
                publisher="MistralAI",
                family=family,
                version="1",
                capacity=ModelEndpointCapacity(unit=ModelCapacityUnit.TPM, value=1_000),
                features=ModelEndpointFeatures(streaming=True, structured_output=True),
                discovery=ModelEndpointDiscovery(
                    source=ModelDiscoverySource.AZURE_MANAGEMENT,
                    resource_ref_digest="a" * 64,
                    verified_at=datetime(2026, 8, 28, tzinfo=UTC),
                ),
            ),
        ),
    )


def _require(gate: ModuleType, resolved: ResolvedModels) -> None:
    gate.require_resolved_capability(
        resolved,
        capability="t2.reasoner.secondary",
        publisher="MistralAI",
        family="Mistral-Large-3",
        version="1",
        sku="GlobalStandard",
        minimum_capacity_tpm=1_000,
        provider_kind=ModelProviderKind.AZURE_FOUNDRY,
        endpoint_ref="azure-foundry:aif-fdai-models-staging-krc",
    )


def test_accepts_exact_resolved_foundry_secondary(gate: ModuleType) -> None:
    _require(gate, _resolved())


def test_apply_validation_mode_must_match_protected_plan(gate: ModuleType) -> None:
    metadata = {"model_resolution": {"chatops_channel_validation": True}}

    assert gate.chatops_validation_required(metadata, requested=True)
    with pytest.raises(gate.CapabilityRequirementError, match="does not match"):
        gate.chatops_validation_required(metadata, requested=False)


def test_apply_without_model_resolution_skips_unrequested_validation(gate: ModuleType) -> None:
    assert not gate.chatops_validation_required({}, requested=False)


@pytest.mark.parametrize(
    ("resolved", "message"),
    [
        (_resolved(status=CapabilityStatus.HIL_ONLY), "not resolved"),
        (_resolved(family="Mistral-Large-2"), "approved profile"),
        (_resolved(endpoint_ref="azure-foundry:wrong"), "endpoint binding"),
    ],
)
def test_rejects_unavailable_or_mismatched_secondary(
    gate: ModuleType,
    resolved: ResolvedModels,
    message: str,
) -> None:
    with pytest.raises(gate.CapabilityRequirementError, match=message):
        _require(gate, resolved)
