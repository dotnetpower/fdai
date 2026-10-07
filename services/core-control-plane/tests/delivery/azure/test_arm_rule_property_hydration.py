"""Extension reads add normalized Rule properties and leave failures unobserved."""

from __future__ import annotations

import httpx
from fdai.delivery.azure.arm_rule_property_hydration import (
    ArmRulePropertyHydrator,
    project_diagnostic_settings,
)
from fdai.delivery.azure.inventory import ResourceQueryResult
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

_RG = "/subscriptions/sub-1/resourceGroups/rg-1/providers"
STORAGE = f"{_RG}/Microsoft.Storage/storageAccounts/st1"
VAULT = f"{_RG}/Microsoft.KeyVault/vaults/kv1"
SQL = f"{_RG}/Microsoft.Sql/servers/sql1/databases/db1"
FLEXIBLE = f"{_RG}/Microsoft.DBforPostgreSQL/flexibleServers/pg1"
DIAGNOSTICS = "/providers/Microsoft.Insights/diagnosticSettings"


def _identity() -> StaticWorkloadIdentity:
    return StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="test-token",  # noqa: S106 - deterministic test credential
    )


def _resource(resource_type: str, provider_ref: str, **props: object) -> ResourceRecord:
    return ResourceRecord(
        resource_id=provider_ref.casefold(),
        type=resource_type,
        props={"providerType": provider_ref.split("/providers/")[1].rsplit("/", 1)[0], **props},
        provider_ref=provider_ref,
    )


def _hydrator(client: httpx.AsyncClient, *, max_reads: int = 100) -> ArmRulePropertyHydrator:
    return ArmRulePropertyHydrator(
        identity=_identity(),
        http_client=client,
        arm_endpoint="https://management.azure.com",
        audience="https://management.azure.com/.default",
        timeout_seconds=5.0,
        max_response_bytes=1_000_000,
        max_attempts=1,
        max_reads=max_reads,
    )


_ROUTED = {
    "workspaceId": "/subscriptions/sub-1/workspaces/law",
    "logs": [{"category": "AuditEvent", "enabled": True}],
}


def _handler(requested: list[str]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requested.append(path)
        assert request.headers["Authorization"] == "Bearer test-token"
        if path == f"{STORAGE}/blobServices/default":
            return httpx.Response(
                200,
                json={
                    "properties": {
                        "deleteRetentionPolicy": {"enabled": True, "days": 7},
                        "isVersioningEnabled": False,
                    }
                },
            )
        if (
            path
            == f"{STORAGE}/blobServices/default/providers/Microsoft.Insights/diagnosticSettings"
        ):
            return httpx.Response(200, json={"value": [{"properties": _ROUTED}]})
        if path == f"{VAULT}/providers/Microsoft.Insights/diagnosticSettings":
            return httpx.Response(200, json={"value": []})
        if path == f"{SQL}/providers/Microsoft.Insights/diagnosticSettings":
            return httpx.Response(403, json={"error": {"code": "AuthorizationFailed"}})
        if path == f"{SQL}/transparentDataEncryption/current":
            return httpx.Response(200, json={"properties": {"state": "Enabled"}})
        if path == f"{FLEXIBLE}/providers/Microsoft.Insights/diagnosticSettings":
            return httpx.Response(200, json={"value": []})
        if path == f"{FLEXIBLE}/configurations/require_secure_transport":
            return httpx.Response(200, json={"properties": {"value": "ON"}})
        return httpx.Response(404, json={})

    return httpx.MockTransport(handle)


async def test_hydrates_extension_properties_and_leaves_failed_reads_unobserved() -> None:
    requested: list[str] = []
    resources = (
        _resource("object-storage", STORAGE),
        _resource("secret-store", VAULT),
        _resource("sql-database", SQL),
        _resource("postgresql-server", FLEXIBLE),
        _resource("network.nsg", f"{_RG}/Microsoft.Network/networkSecurityGroups/nsg1"),
    )
    async with httpx.AsyncClient(transport=_handler(requested)) as client:
        result = await _hydrator(client).hydrate(ResourceQueryResult(resources=resources))

    by_type = {item.type: item.props for item in result.resources}
    assert by_type["object-storage"]["blob_soft_delete_enabled"] is True
    assert by_type["object-storage"]["blob_versioning_enabled"] is False
    assert by_type["object-storage"]["diagnostic_settings"] == [
        {"destinations": ["workspaceId"], "enabled_categories": 1}
    ]
    assert by_type["secret-store"]["diagnostic_settings"] == []
    # A denied read is not evidence of absence: the property stays unobserved.
    assert "diagnostic_settings" not in by_type["sql-database"]
    assert by_type["sql-database"]["tde_enabled"] is True
    assert by_type["postgresql-server"]["ssl_enforcement"] == "enabled"
    assert "security_rules" not in by_type["network.nsg"]
    assert not any("networkSecurityGroups" in path for path in requested)


async def test_row_values_win_and_bounds_and_truncation_skip_reads() -> None:
    requested: list[str] = []
    observed = _resource("secret-store", VAULT, diagnostic_settings=[{"destinations": ["x"]}])
    truncated = _resource("object-storage", STORAGE, _truncated=True)
    single = _resource("postgresql-server", f"{_RG}/Microsoft.DBforPostgreSQL/servers/pg-single")
    async with httpx.AsyncClient(transport=_handler(requested)) as client:
        result = await _hydrator(client, max_reads=1).hydrate(
            ResourceQueryResult(resources=(observed, truncated, single))
        )

    assert result.resources[0].props["diagnostic_settings"] == [{"destinations": ["x"]}]
    assert result.resources[1] == truncated
    # The single server needs one diagnostics read but the budget is spent; no partial reads.
    assert requested == [f"{VAULT}/providers/Microsoft.Insights/diagnosticSettings"]
    assert result.resources[2] == single


def test_settings_without_destination_or_enabled_category_do_not_count() -> None:
    payload = {
        "value": [
            {"properties": {"logs": [{"enabled": True}]}},
            {"properties": {"workspaceId": "w", "logs": [{"enabled": False}]}},
            {"properties": {"storageAccountId": "s", "metrics": [{"enabled": True}]}},
        ]
    }

    assert project_diagnostic_settings(payload) == {
        "diagnostic_settings": [{"destinations": ["storageAccountId"], "enabled_categories": 1}]
    }
    assert project_diagnostic_settings({"value": [{"name": "broken"}]}) == {}
    assert project_diagnostic_settings({}) == {}
