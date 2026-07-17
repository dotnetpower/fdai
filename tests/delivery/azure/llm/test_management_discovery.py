"""Azure CLI model endpoint management discovery tests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from fdai.delivery.azure.llm.management_discovery import (
    ApimEndpointDiscoverySpec,
    AzureCliApimEndpointSource,
    AzureCliOpenAIEndpointSource,
    AzureOpenAIDiscoverySpec,
)
from fdai.delivery.azure.llm.resolver_queries import AzureCliResolverError
from fdai.rule_catalog.schema.model_endpoint import (
    ModelApiStyle,
    ModelCapacityUnit,
    ModelEndpointCapacity,
    ModelEndpointFeatures,
    ModelProviderKind,
)


class _Runner:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str]) -> str:
        self.calls.append(tuple(argv))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return json.dumps(response)


def _clock() -> datetime:
    return datetime(2026, 7, 17, tzinfo=UTC)


async def test_discovers_direct_standard_and_ptu_deployments() -> None:
    account = {
        "id": (
            "/subscriptions/example/resourceGroups/rg/providers/"
            "Microsoft.CognitiveServices/accounts/oai"
        ),
        "kind": "OpenAI",
    }
    deployments = [
        {
            "id": account["id"] + "/deployments/t1.embedding",
            "name": "t1.embedding",
            "properties": {
                "provisioningState": "Succeeded",
                "model": {
                    "format": "OpenAI",
                    "name": "text-embedding-3-small",
                    "version": "1",
                },
            },
            "sku": {"name": "Standard", "capacity": 100},
        },
        {
            "id": account["id"] + "/deployments/t2.reasoner.primary",
            "name": "t2.reasoner.primary",
            "properties": {
                "provisioningState": "Succeeded",
                "model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-08-06"},
            },
            "sku": {"name": "GlobalProvisionedManaged", "capacity": 30},
        },
    ]
    source = AzureCliOpenAIEndpointSource(
        resource_group="rg-example",
        account_name="oai-example",
        specs=(
            AzureOpenAIDiscoverySpec(
                capability="t1.embedding",
                deployment="t1.embedding",
                features=ModelEndpointFeatures(embeddings=True),
            ),
            AzureOpenAIDiscoverySpec(
                capability="t2.reasoner.primary",
                deployment="t2.reasoner.primary",
                features=ModelEndpointFeatures(structured_output=True, tool_calling=True),
            ),
        ),
        runner=_Runner(account, deployments),
        observed_at=_clock,
    )

    observations = await source.list_observations()

    assert [item.capability for item in observations] == ["t1.embedding", "t2.reasoner.primary"]
    assert observations[0].capacity_unit is ModelCapacityUnit.TPM
    assert observations[0].capacity_value == 100_000
    assert observations[1].capacity_unit is ModelCapacityUnit.PTU
    assert observations[1].capacity_value == 30


def _apim_spec() -> ApimEndpointDiscoverySpec:
    return ApimEndpointDiscoverySpec(
        resource_group="rg-example",
        service_name="apim-example",
        api_id="fdai-t2-primary",
        capability="t2.reasoner.primary",
        endpoint_ref="apim:t2-primary",
        deployment="gpt-4o",
        auth_audience="api://fdai-model-gateway",
        publisher="OpenAI",
        family="gpt-4o",
        version="2024-08-06",
        capacity=ModelEndpointCapacity(unit=ModelCapacityUnit.PTU, value=30),
        features=ModelEndpointFeatures(streaming=True, structured_output=True),
        ptu_backend_id="primary-ptu",
        standard_backend_id="primary-standard",
        provider_kind=ModelProviderKind.AZURE_OPENAI,
        api_style=ModelApiStyle.OPENAI_V1,
    )


def _policy() -> str:
    return (
        "<policies><inbound><authentication-managed-identity />"
        "<set-backend-service backend-id='primary-ptu' /></inbound>"
        "<backend><retry condition='@(context.Response.StatusCode == 429)'>"
        "<set-backend-service backend-id='primary-standard' /></retry></backend>"
        "<outbound><set-header name='x-fdai-model-backend' />"
        "<set-header name='x-fdai-capacity-unit' />"
        "<set-header name='x-fdai-spillover' /></outbound></policies>"
    )


async def test_discovers_apim_only_after_api_backends_and_policy_verify() -> None:
    runner = _Runner(
        {"id": "/subscriptions/example/providers/Microsoft.ApiManagement/service/apim/apis/api"},
        {"name": "primary-ptu"},
        {"name": "primary-standard"},
        {"value": _policy()},
    )
    source = AzureCliApimEndpointSource(spec=_apim_spec(), runner=runner, observed_at=_clock)

    observations = await source.list_observations()

    assert len(runner.calls) == 4
    assert observations[0].route_kind.value == "apim-gateway"
    assert observations[0].capacity_unit is ModelCapacityUnit.PTU
    assert observations[0].source.value == "apim-management"


async def test_apim_discovery_rejects_policy_without_route_evidence() -> None:
    runner = _Runner(
        {"id": "/subscriptions/example/providers/Microsoft.ApiManagement/service/apim/apis/api"},
        {"name": "primary-ptu"},
        {"name": "primary-standard"},
        {"value": "<policies>primary-ptu primary-standard StatusCode == 429</policies>"},
    )
    source = AzureCliApimEndpointSource(spec=_apim_spec(), runner=runner, observed_at=_clock)

    with pytest.raises(AzureCliResolverError, match="lacks required FDAI controls"):
        await source.list_observations()
