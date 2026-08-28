"""Azure Resource Graph configuration observation adapter tests."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fdai.delivery.azure.configuration_drift import (
    AzureArgConfigurationObservationSource,
    AzureConfigurationObservationConfig,
    AzureConfigurationObservationError,
)
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity
from pydantic import TypeAdapter

_NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)
_AUDIENCE = "https://management.azure.com/.default"


def _config(**overrides: object) -> AzureConfigurationObservationConfig:
    values: dict[str, object] = {
        "allowed_scope": "scope:example-platform",
        "subscription_scopes": ("00000000-0000-0000-0000-000000000001",),
        "attribute_paths": ("properties.publicNetworkAccess", "sku.name", "tags.owner"),
        "page_size": 100,
        "max_pages": 2,
        "max_records": 100,
        "timeout_seconds": 5.0,
    }
    values.update(overrides)
    return TypeAdapter(AzureConfigurationObservationConfig).validate_python(values)


def _identity() -> StaticWorkloadIdentity:
    return StaticWorkloadIdentity(
        audience=_AUDIENCE,
        token="test-token",  # noqa: S106 - inert test credential
    )


async def test_observation_projects_selected_attributes_and_unknowns() -> None:
    captured_query = ""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_query
        payload = request.read().decode("utf-8")
        captured_query = payload
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": (
                            "/subscriptions/example/resourceGroups/rg/providers/Example/widgets/a"
                        ),
                        "type": "Example/widgets",
                        "name": "widget-a",
                        "location": "koreacentral",
                        "attribute_0_present": True,
                        "attribute_0": "Disabled",
                        "attribute_1_present": True,
                        "attribute_1": "Standard",
                        "attribute_2_present": False,
                        "attribute_2": "",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AzureArgConfigurationObservationSource(
            identity=_identity(),
            http_client=client,
            config=_config(),
            clock=lambda: _NOW,
        )
        observation = await source.observe(scope="scope:example-platform")

    resource = observation.resources[0]
    assert observation.scope == "scope:example-platform"
    assert observation.source == "azure_resource_graph"
    assert observation.completeness.value == "complete"
    assert resource.local_name.startswith("widget-a#")
    assert resource.attributes == {
        "properties.publicNetworkAccess": "Disabled",
        "sku.name": "Standard",
    }
    assert resource.unknown_attributes == frozenset({"tags.owner"})
    assert "properties.publicNetworkAccess" in captured_query
    assert "isnotnull(properties.publicNetworkAccess)" in captured_query
    assert "/subscriptions/example" not in captured_query


async def test_scope_escape_is_rejected_before_provider_io() -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AzureArgConfigurationObservationSource(
            identity=_identity(),
            http_client=client,
            config=_config(),
        )
        with pytest.raises(PermissionError, match="outside"):
            await source.observe(scope="scope:another-platform")

    assert called is False


async def test_global_resource_normalizes_empty_location() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "/subscriptions/example/providers/Example/widgets/a",
                        "type": "Example/widgets",
                        "name": "widget-a",
                        "location": "",
                        "attribute_0_present": True,
                        "attribute_0": "Disabled",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AzureArgConfigurationObservationSource(
            identity=_identity(),
            http_client=client,
            config=_config(attribute_paths=("properties.publicNetworkAccess",)),
            clock=lambda: _NOW,
        )
        observation = await source.observe(scope="scope:example-platform")

    assert observation.resources[0].region == "global"


async def test_truncated_result_fails_without_partial_observation() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [],
                "resultTruncated": True,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AzureArgConfigurationObservationSource(
            identity=_identity(),
            http_client=client,
            config=_config(),
        )
        with pytest.raises(AzureConfigurationObservationError, match="truncated"):
            await source.observe(scope="scope:example-platform")


@pytest.mark.parametrize(
    "row",
    (
        {
            "id": "/subscriptions/example/providers/Example/widgets/a",
            "type": "Example/widgets",
            "name": "widget-a",
            "location": "koreacentral",
            "attribute_0_present": "true",
        },
        {
            "id": "/subscriptions/example/providers/Example/widgets/a",
            "type": "Example/widgets",
            "name": "widget-a",
            "location": "koreacentral",
            "attribute_0_present": True,
            "attribute_0": "x" * 4_097,
        },
    ),
)
async def test_malformed_or_oversized_attributes_fail_closed(
    row: dict[str, object],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [row]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AzureArgConfigurationObservationSource(
            identity=_identity(),
            http_client=client,
            config=_config(attribute_paths=("properties.publicNetworkAccess",)),
        )
        with pytest.raises(AzureConfigurationObservationError):
            await source.observe(scope="scope:example-platform")


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"subscription_scopes": ()}, "subscription_scopes"),
        ({"attribute_paths": ()}, "attribute_paths"),
        ({"attribute_paths": ("tags.owner", "properties.value")}, "ordered"),
        ({"attribute_paths": ("properties.value; drop",)}, "invalid path"),
        ({"max_records": 0}, "bounds"),
        ({"arg_endpoint": "https://management.example.com"}, "approved Azure"),
    ),
)
def test_config_rejects_invalid_or_ambiguous_bounds(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises((ValueError, TypeError), match=message):
        _config(**overrides)
