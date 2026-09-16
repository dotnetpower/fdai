"""Bounded Azure Diagnostic Settings and App Insights workspace resolution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.azure.deployment_history import AzureResolvedResourceIdentity
from fdai.delivery.azure.telemetry_workspace import (
    AzureMonitorTelemetryWorkspaceConfig,
    AzureMonitorTelemetryWorkspaceResolver,
    AzureTelemetryWorkspaceError,
)
from fdai.shared.providers.workload_identity import IdentityToken

_NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
_SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
_CUSTOMER_ID = "00000000-0000-0000-0000-000000000000"
_RESOURCE_ID = (
    f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-example/"
    "providers/Microsoft.Compute/virtualMachines/vm-example"
)
_COMPONENT_ID = (
    f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-example/"
    "providers/Microsoft.Insights/components/app-example"
)
_WORKSPACE_ID = (
    f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-monitor/"
    "providers/Microsoft.OperationalInsights/workspaces/log-example"
)


def _diagnostic_setting(
    name: str,
    *,
    workspace_id: str | None = None,
) -> dict[str, object]:
    properties: dict[str, str] = {}
    if workspace_id is not None:
        properties["workspaceId"] = workspace_id
    return {
        "id": (f"{_RESOURCE_ID}/providers/Microsoft.Insights/diagnosticSettings/{name}"),
        "type": "Microsoft.Insights/diagnosticSettings",
        "properties": properties,
    }


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",
            expires_at=_NOW + timedelta(hours=1),
            audience=audience,
        )


class _ResourceIdentities:
    def __init__(self, provider_id: str) -> None:
        self._provider_id = provider_id

    async def resolve(
        self,
        resource_ref: str,
        *,
        at: datetime | None = None,
    ) -> AzureResolvedResourceIdentity | None:
        assert resource_ref == "resource-neutral"
        assert at == _NOW
        return AzureResolvedResourceIdentity(
            provider_resource_id=self._provider_id,
            inventory_generation="inventory-generation",
        )


class _MissingResourceIdentities:
    async def resolve(
        self,
        resource_ref: str,
        *,
        at: datetime | None = None,
    ) -> AzureResolvedResourceIdentity | None:
        del resource_ref, at
        return None


class _FailingIdentity:
    async def get_token(self, audience: str) -> IdentityToken:
        raise RuntimeError(f"identity unavailable for {audience}")


class _FailingResourceIdentities:
    async def resolve(
        self,
        resource_ref: str,
        *,
        at: datetime | None = None,
    ) -> AzureResolvedResourceIdentity | None:
        raise RuntimeError(f"inventory unavailable for {resource_ref} at {at}")


def _resolver(provider_id: str, handler: object) -> AzureMonitorTelemetryWorkspaceResolver:
    return AzureMonitorTelemetryWorkspaceResolver(
        identity=_Identity(),
        resource_identities=_ResourceIdentities(provider_id),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),  # type: ignore[arg-type]
    )


async def test_resolves_diagnostic_setting_workspace_and_deduplicates_routes() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer test-token"
        if request.url.path.endswith("/providers/Microsoft.Insights/diagnosticSettings"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        _diagnostic_setting("primary", workspace_id=_WORKSPACE_ID),
                        _diagnostic_setting("duplicate", workspace_id=_WORKSPACE_ID),
                        _diagnostic_setting("storage-only"),
                    ]
                },
            )
        assert request.url.path.casefold() == _WORKSPACE_ID.casefold()
        return httpx.Response(
            200,
            json={
                "id": _WORKSPACE_ID,
                "type": "Microsoft.OperationalInsights/workspaces",
                "properties": {"customerId": _CUSTOMER_ID},
            },
        )

    resolution = await _resolver(_RESOURCE_ID, handler).resolve(
        "resource-neutral",
        at=_NOW,
    )

    assert resolution.provider_resource_id == _RESOURCE_ID
    assert resolution.inventory_generation == "inventory-generation"
    assert resolution.workspace_ids == (_CUSTOMER_ID,)
    assert len(requests) == 2


async def test_resolves_workspace_based_application_insights_component() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/providers/Microsoft.Insights/diagnosticSettings"):
            return httpx.Response(200, json={"value": []})
        if request.url.path.casefold() == _COMPONENT_ID.casefold():
            return httpx.Response(
                200,
                json={
                    "id": _COMPONENT_ID,
                    "type": "Microsoft.Insights/components",
                    "properties": {"WorkspaceResourceId": _WORKSPACE_ID},
                },
            )
        return httpx.Response(
            200,
            json={
                "id": _WORKSPACE_ID,
                "type": "Microsoft.OperationalInsights/workspaces",
                "properties": {"customerId": _CUSTOMER_ID},
            },
        )

    resolution = await _resolver(_COMPONENT_ID, handler).resolve(
        "resource-neutral",
        at=_NOW,
    )
    assert resolution.workspace_ids == (_CUSTOMER_ID,)


async def test_route_overflow_fails_before_workspace_reads() -> None:
    workspace_reads = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal workspace_reads
        if request.url.path.endswith("/providers/Microsoft.Insights/diagnosticSettings"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "properties": {
                                "workspaceId": _WORKSPACE_ID.replace(
                                    "log-example", f"log-example-{index}"
                                )
                            },
                            "id": (
                                f"{_RESOURCE_ID}/providers/Microsoft.Insights/"
                                f"diagnosticSettings/route-{index}"
                            ),
                            "type": "Microsoft.Insights/diagnosticSettings",
                        }
                        for index in range(5)
                    ]
                },
            )
        workspace_reads += 1
        return httpx.Response(500)

    resolver = AzureMonitorTelemetryWorkspaceResolver(
        identity=_Identity(),
        resource_identities=_ResourceIdentities(_RESOURCE_ID),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        config=AzureMonitorTelemetryWorkspaceConfig(maximum_workspaces=3),
    )
    with pytest.raises(AzureTelemetryWorkspaceError, match="route count"):
        await resolver.resolve("resource-neutral", at=_NOW)
    assert workspace_reads == 0


async def test_workspace_identity_mismatch_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/providers/Microsoft.Insights/diagnosticSettings"):
            return httpx.Response(
                200,
                json={"value": [_diagnostic_setting("primary", workspace_id=_WORKSPACE_ID)]},
            )
        return httpx.Response(
            200,
            json={
                "id": _WORKSPACE_ID.replace("log-example", "log-other"),
                "type": "Microsoft.OperationalInsights/workspaces",
                "properties": {"customerId": _CUSTOMER_ID},
            },
        )

    with pytest.raises(AzureTelemetryWorkspaceError, match="identity mismatch"):
        await _resolver(_RESOURCE_ID, handler).resolve("resource-neutral", at=_NOW)


@pytest.mark.parametrize(
    "provider_id",
    (
        "resource-not-arm",
        _RESOURCE_ID + "?api-version=unsafe",
        _RESOURCE_ID + "/",
        _RESOURCE_ID.replace(_SUBSCRIPTION, "not-a-guid"),
    ),
)
async def test_invalid_provider_identity_fails_before_arm(provider_id: str) -> None:
    resolver = _resolver(
        provider_id,
        lambda _request: pytest.fail("unexpected ARM request"),
    )
    with pytest.raises(AzureTelemetryWorkspaceError, match="bounded ARM id"):
        await resolver.resolve("resource-neutral", at=_NOW)


async def test_missing_inventory_identity_fails_before_arm() -> None:
    resolver = AzureMonitorTelemetryWorkspaceResolver(
        identity=_Identity(),
        resource_identities=_MissingResourceIdentities(),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: pytest.fail("unexpected ARM request"))
        ),
    )
    with pytest.raises(AzureTelemetryWorkspaceError, match="identity is unavailable"):
        await resolver.resolve("resource-neutral", at=_NOW)


async def test_identity_failure_prevents_arm_request() -> None:
    resolver = AzureMonitorTelemetryWorkspaceResolver(
        identity=_FailingIdentity(),
        resource_identities=_ResourceIdentities(_RESOURCE_ID),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: pytest.fail("unexpected ARM request"))
        ),
    )
    with pytest.raises(AzureTelemetryWorkspaceError, match="workspace identity failed"):
        await resolver.resolve("resource-neutral", at=_NOW)


@pytest.mark.parametrize(
    ("response", "message"),
    (
        (httpx.Response(403), "HTTP 403"),
        (httpx.Response(200, text="not-json"), "not JSON"),
        (
            httpx.Response(200, json={"value": [], "nextLink": "https://example.com/next"}),
            "partial",
        ),
    ),
)
async def test_diagnostic_response_failures_are_explicit(
    response: httpx.Response,
    message: str,
) -> None:
    resolver = _resolver(_RESOURCE_ID, lambda _request: response)
    with pytest.raises(AzureTelemetryWorkspaceError, match=message):
        await resolver.resolve("resource-neutral", at=_NOW)


async def test_oversized_diagnostic_response_fails_closed() -> None:
    resolver = AzureMonitorTelemetryWorkspaceResolver(
        identity=_Identity(),
        resource_identities=_ResourceIdentities(_RESOURCE_ID),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, content=b"{" + b" " * 128 + b"}")
            )
        ),
        config=AzureMonitorTelemetryWorkspaceConfig(maximum_response_bytes=64),
    )
    with pytest.raises(AzureTelemetryWorkspaceError, match="exceeded limit"):
        await resolver.resolve("resource-neutral", at=_NOW)


@pytest.mark.parametrize(
    "config",
    (
        AzureMonitorTelemetryWorkspaceConfig(
            endpoint="https://management.usgovcloudapi.net",
            audience="https://management.usgovcloudapi.net/.default",
        ),
        AzureMonitorTelemetryWorkspaceConfig(
            endpoint="https://management.chinacloudapi.cn",
            audience="https://management.chinacloudapi.cn/.default",
        ),
    ),
)
def test_supported_sovereign_cloud_configs(config: AzureMonitorTelemetryWorkspaceConfig) -> None:
    assert config.endpoint.startswith("https://management.")


def test_workspace_limit_reserves_one_static_fallback_route() -> None:
    with pytest.raises(ValueError, match=r"\[1, 3\]"):
        AzureMonitorTelemetryWorkspaceConfig(maximum_workspaces=4)


@pytest.mark.parametrize(
    "kwargs",
    (
        {"provider_resource_id": "", "inventory_generation": "generation", "workspace_ids": ()},
        {"provider_resource_id": _RESOURCE_ID, "inventory_generation": "", "workspace_ids": ()},
        {
            "provider_resource_id": _RESOURCE_ID,
            "inventory_generation": "generation",
            "workspace_ids": ("workspace", "workspace"),
        },
        {
            "provider_resource_id": _RESOURCE_ID,
            "inventory_generation": "generation",
            "workspace_ids": ("workspace-b", "workspace-a"),
        },
    ),
)
def test_resolution_contract_rejects_invalid_identity_or_routes(
    kwargs: dict[str, object],
) -> None:
    from fdai.delivery.azure.telemetry_workspace import AzureTelemetryWorkspaceResolution

    with pytest.raises(ValueError):
        AzureTelemetryWorkspaceResolution(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"endpoint": "http://management.azure.com"}, "approved Azure origin"),
        ({"audience": "https://wrong.example.com/.default"}, "audience"),
        ({"diagnostic_settings_api_version": "latest"}, "dated Azure versions"),
        ({"timeout_seconds": 0.0}, "timeout_seconds"),
        ({"maximum_workspaces": 0}, "maximum_workspaces"),
        ({"maximum_response_bytes": 0}, "response byte bound"),
    ),
)
def test_config_rejects_invalid_boundaries(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        AzureMonitorTelemetryWorkspaceConfig(**kwargs)  # type: ignore[arg-type]


async def test_inventory_provider_failure_is_normalized() -> None:
    resolver = AzureMonitorTelemetryWorkspaceResolver(
        identity=_Identity(),
        resource_identities=_FailingResourceIdentities(),
        http_client=httpx.AsyncClient(),
    )
    with pytest.raises(AzureTelemetryWorkspaceError, match="identity resolution failed"):
        await resolver.resolve("resource-neutral", at=_NOW)


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"value": ["not-a-row"]},
        {
            "value": [
                {
                    "id": "wrong",
                    "type": "Microsoft.Insights/diagnosticSettings",
                    "properties": {},
                }
            ]
        },
        {
            "value": [
                {
                    "id": (
                        f"{_RESOURCE_ID}/providers/Microsoft.Insights/diagnosticSettings/primary"
                    ),
                    "type": "Microsoft.Insights/diagnosticSettings",
                    "properties": {"workspaceId": 42},
                }
            ]
        },
        {"value": [_diagnostic_setting("primary", workspace_id=_RESOURCE_ID)]},
    ),
)
async def test_malformed_diagnostic_rows_fail_closed(payload: dict[str, object]) -> None:
    resolver = _resolver(_RESOURCE_ID, lambda _request: httpx.Response(200, json=payload))
    with pytest.raises(AzureTelemetryWorkspaceError):
        await resolver.resolve("resource-neutral", at=_NOW)


@pytest.mark.parametrize(
    "properties",
    (
        None,
        {"WorkspaceResourceId": 42},
    ),
)
async def test_malformed_application_insights_workspace_fails_closed(
    properties: object,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/providers/Microsoft.Insights/diagnosticSettings"):
            return httpx.Response(200, json={"value": []})
        return httpx.Response(
            200,
            json={
                "id": _COMPONENT_ID,
                "type": "Microsoft.Insights/components",
                "properties": properties,
            },
        )

    with pytest.raises(AzureTelemetryWorkspaceError, match="Application Insights"):
        await _resolver(_COMPONENT_ID, handler).resolve("resource-neutral", at=_NOW)


async def test_legacy_application_insights_without_workspace_uses_no_dynamic_route() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/providers/Microsoft.Insights/diagnosticSettings"):
            return httpx.Response(200, json={"value": []})
        return httpx.Response(
            200,
            json={
                "id": _COMPONENT_ID,
                "type": "Microsoft.Insights/components",
                "properties": {},
            },
        )

    resolution = await _resolver(_COMPONENT_ID, handler).resolve("resource-neutral", at=_NOW)
    assert resolution.workspace_ids == ()
    assert len(requests) == 2


@pytest.mark.parametrize(
    "properties",
    (
        {},
        {"customerId": "not-a-guid"},
    ),
)
async def test_malformed_workspace_customer_identity_fails_closed(
    properties: dict[str, object],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/providers/Microsoft.Insights/diagnosticSettings"):
            return httpx.Response(
                200,
                json={"value": [_diagnostic_setting("primary", workspace_id=_WORKSPACE_ID)]},
            )
        return httpx.Response(
            200,
            json={
                "id": _WORKSPACE_ID,
                "type": "Microsoft.OperationalInsights/workspaces",
                "properties": properties,
            },
        )

    with pytest.raises(AzureTelemetryWorkspaceError, match="workspace"):
        await _resolver(_RESOURCE_ID, handler).resolve("resource-neutral", at=_NOW)


async def test_arm_transport_failure_is_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    with pytest.raises(AzureTelemetryWorkspaceError, match="ARM request failed"):
        await _resolver(_RESOURCE_ID, handler).resolve("resource-neutral", at=_NOW)
