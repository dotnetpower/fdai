"""Azure Resource Graph configuration observation adapter tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest
from fdai.delivery.azure.configuration_drift import (
    AzureArgConfigurationObservationSource,
    AzureBlobConfigurationBaselineConfig,
    AzureBlobConfigurationBaselineSource,
    AzureConfigurationBaselineError,
    AzureConfigurationObservationConfig,
    AzureConfigurationObservationError,
)
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity
from pydantic import TypeAdapter

_NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)
_AUDIENCE = "https://management.azure.com/.default"
_STORAGE_AUDIENCE = "https://storage.azure.com/"


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


def _baseline_payload() -> tuple[bytes, str]:
    payload = json.dumps(
        {
            "schema_version": "1.0.0",
            "version": "example-v1",
            "created_at": "2026-08-28T12:00:00+00:00",
            "scope": "scope:example-platform",
            "source": "reviewed snapshot",
            "document_sha256": "a" * 64,
            "resources": [],
            "links": [],
            "allowed_exceptions": [],
            "unknown_items": [],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return payload, hashlib.sha256(payload).hexdigest()


async def test_blob_baseline_source_requires_managed_identity_and_exact_digest() -> None:
    payload, digest = _baseline_payload()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(
            200,
            headers={"x-ms-meta-fdai_sha256": digest},
            content=payload,
        )

    identity = StaticWorkloadIdentity(
        audience=_STORAGE_AUDIENCE,
        token="test-token",  # noqa: S106 - inert test credential
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AzureBlobConfigurationBaselineSource(
            identity=identity,
            http_client=client,
            config=AzureBlobConfigurationBaselineConfig(
                blob_url=(
                    "https://example.blob.core.windows.net/decision-evidence/"
                    f"configuration-baselines/{digest}.json"
                ),
                expected_sha256=digest,
            ),
        )

        baseline = await source.load()

    assert baseline.version == "example-v1"
    assert baseline.sha256 == digest


async def test_blob_baseline_source_rejects_metadata_or_content_mismatch() -> None:
    payload, digest = _baseline_payload()
    identity = StaticWorkloadIdentity(
        audience=_STORAGE_AUDIENCE,
        token="test-token",  # noqa: S106 - inert test credential
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-ms-meta-fdai_sha256": "b" * 64},
            content=payload,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AzureBlobConfigurationBaselineSource(
            identity=identity,
            http_client=client,
            config=AzureBlobConfigurationBaselineConfig(
                blob_url=(
                    "https://example.blob.core.windows.net/decision-evidence/"
                    f"configuration-baselines/{digest}.json"
                ),
                expected_sha256=digest,
            ),
        )
        with pytest.raises(AzureConfigurationBaselineError, match="metadata"):
            await source.load()


@pytest.mark.parametrize(
    "blob_url",
    (
        "http://example.blob.core.windows.net/container/configuration-baselines/"
        + "a" * 64
        + ".json",
        "https://example.com/container/configuration-baselines/" + "a" * 64 + ".json",
        "https://example.blob.core.windows.net/container/other/" + "a" * 64 + ".json",
    ),
)
def test_blob_baseline_config_rejects_non_azure_or_unpinned_urls(blob_url: str) -> None:
    with pytest.raises(ValueError, match="content-addressed Azure Blob"):
        AzureBlobConfigurationBaselineConfig(
            blob_url=blob_url,
            expected_sha256="a" * 64,
        )


async def test_observation_projects_selected_attributes_and_unknowns() -> None:
    captured_query = ""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_query
        payload = request.read().decode("utf-8")
        captured_query = json.loads(payload)["query"]
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
                        "attribute_0_presence": "present",
                        "attribute_0": "",
                        "attribute_1_presence": "present",
                        "attribute_1": "Standard",
                        "attribute_2_presence": "missing",
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
        "properties.publicNetworkAccess": "",
        "sku.name": "Standard",
    }
    assert resource.unknown_attributes == frozenset({"tags.owner"})
    assert "properties.publicNetworkAccess" in captured_query
    assert 'iff(isnull(properties.publicNetworkAccess), "missing", "present")' in captured_query
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
                        "attribute_0_presence": "present",
                        "attribute_0": "",
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
    assert observation.resources[0].attributes == {"properties.publicNetworkAccess": ""}


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
            "attribute_0_presence": "true",
        },
        {
            "id": "/subscriptions/example/providers/Example/widgets/a",
            "type": "Example/widgets",
            "name": "widget-a",
            "location": "koreacentral",
            "attribute_0_presence": "present",
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
