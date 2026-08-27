from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    ResolvedCapability,
    ResolvedModels,
)
from fdai.rule_catalog.schema.model_endpoint import (
    ModelApiStyle,
    ModelProviderKind,
)
from scripts.deployment.azure.seal_model_endpoint_bindings import (
    seal_partner_bindings,
)


def _resolved(*capabilities: ResolvedCapability) -> ResolvedModels:
    return ResolvedModels(
        schema_version="1.0.0",
        region="koreacentral",
        subscription_id="00000000-0000-0000-0000-000000000000",
        deployer_object_id="00000000-0000-0000-0000-000000000001",
        mixed_model_mode="azure-foundry",
        capabilities=capabilities,
    )


def _capability(
    *,
    name: str,
    publisher: str,
    family: str,
) -> ResolvedCapability:
    return ResolvedCapability(
        name=name,
        status=CapabilityStatus.RESOLVED,
        publisher=publisher,
        family=family,
        sku="GlobalStandard",
        capacity_tpm=1000,
        invocation="always",
        version="1",
    )


def test_seals_only_partner_capabilities_with_deterministic_account_ref() -> None:
    resolved = _resolved(
        _capability(
            name="t2.reasoner.primary",
            publisher="OpenAI",
            family="gpt-4o",
        ),
        _capability(
            name="t2.reasoner.secondary",
            publisher="MistralAI",
            family="Mistral-Large-3",
        ),
    )

    sealed = seal_partner_bindings(
        resolved,
        partner_account_name="aif-fdai-models-dev-krc",
        verified_at=datetime(2026, 8, 28, tzinfo=UTC),
    )

    assert len(sealed.endpoint_bindings) == 1
    binding = sealed.endpoint_bindings[0]
    assert binding.capability == "t2.reasoner.secondary"
    assert binding.provider_kind is ModelProviderKind.AZURE_FOUNDRY
    assert binding.api_style is ModelApiStyle.OPENAI_V1
    assert binding.endpoint_ref == "azure-foundry:aif-fdai-models-dev-krc"
    assert ResolvedModels.from_json(sealed.to_json()) == sealed


def test_rejects_versionless_or_non_tpm_partner_capability() -> None:
    capability = _capability(
        name="t2.reasoner.secondary",
        publisher="MistralAI",
        family="Mistral-Large-3",
    )

    with pytest.raises(ValueError, match="not deployable"):
        seal_partner_bindings(
            _resolved(replace(capability, version=None)),
            partner_account_name="aif-fdai-models-dev-krc",
            verified_at=datetime(2026, 8, 28, tzinfo=UTC),
        )
