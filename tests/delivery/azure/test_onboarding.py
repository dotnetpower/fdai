from __future__ import annotations

import json

import httpx
import pytest

from fdai.core.onboarding import OnboardingProbeError, OnboardingResourceKind
from fdai.delivery.azure.onboarding import AzureOnboardingProbeConfig, AzureResourceProbe
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity


def _config() -> AzureOnboardingProbeConfig:
    return AzureOnboardingProbeConfig(
        subscription_id="00000000-0000-0000-0000-000000000001",
        resource_group="rg-example",
        executor_principal_id="00000000-0000-0000-0000-000000000002",
        event_role_definition_id="event-role",
        secret_role_definition_id="secret-role",
    )


def _identity() -> StaticWorkloadIdentity:
    return StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="test-token",
    )


async def test_probe_maps_resources_and_expected_roles() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if str(body["query"]).startswith("Resources"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"type": "Microsoft.App/containerApps"},
                        {"type": "Microsoft.KeyVault/vaults"},
                        {"type": "Microsoft.App/containerApps"},
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {"roleDefinitionId": "/roles/event-role", "scope": "/subscriptions/x"},
                    {
                        "roleDefinitionId": "/roles/secret-role",
                        "scope": "/providers/Microsoft.KeyVault/vaults/kv-example",
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        probe = AzureResourceProbe(config=_config(), identity=_identity(), http_client=client)
        resources = await probe.observed_resources()
        roles = await probe.observed_role_assignments()

    assert {item.kind for item in resources} == {
        OnboardingResourceKind.RUNTIME,
        OnboardingResourceKind.SECRET_STORE,
    }
    assert {item.role for item in roles} == {
        "event_bus_data_owner",
        "secret_reader",
    }
    assert len(requests) == 2


async def test_probe_fails_closed_on_http_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "denied"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        probe = AzureResourceProbe(config=_config(), identity=_identity(), http_client=client)
        with pytest.raises(OnboardingProbeError, match="HTTP 403"):
            await probe.observed_resources()


async def test_probe_follows_arg_skip_token() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={"data": [{"type": "Microsoft.App/containerApps"}], "$skipToken": "next"},
            )
        return httpx.Response(
            200,
            json={"data": [{"type": "Microsoft.KeyVault/vaults"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        probe = AzureResourceProbe(config=_config(), identity=_identity(), http_client=client)
        resources = await probe.observed_resources()

    assert {item.kind for item in resources} == {
        OnboardingResourceKind.RUNTIME,
        OnboardingResourceKind.SECRET_STORE,
    }
    assert requests[0]["options"] == {"$top": 1000}
    assert requests[1]["options"] == {"$top": 1000, "$skipToken": "next"}


def test_probe_rejects_query_delimiter_in_config() -> None:
    with pytest.raises(ValueError, match="resource_group"):
        AzureOnboardingProbeConfig(
            subscription_id="sub",
            resource_group="bad'group",
            executor_principal_id="principal",
            event_role_definition_id="event",
            secret_role_definition_id="secret",
        )
