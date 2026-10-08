"""Managed identity role assignments come only from a provably complete tenant-wide read."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fdai.delivery.azure.arm_rule_property_hydration import ArmRulePropertyHydrator
from fdai.delivery.azure.inventory import ResourceQueryResult
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.workload_identity import IdentityToken

ARM = "https://management.azure.com"
TENANT = "tenant-example"
ROOT = f"/providers/Microsoft.Management/managementGroups/{TENANT}"
CHILD = "/providers/Microsoft.Management/managementGroups/platform"
SUB = "/subscriptions/sub-1"
OWNER = "/providers/Microsoft.Authorization/roleDefinitions/owner"
WILDCARD = f"{SUB}/providers/Microsoft.Authorization/roleDefinitions/custom-wildcard"
READER = "/providers/Microsoft.Authorization/roleDefinitions/reader"
ASSIGNMENTS = "/providers/Microsoft.Authorization/roleAssignments"


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",  # noqa: S106 - deterministic test credential
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            audience=audience,
        )


def _assignment(name: str, principal: str, definition: str, scope: str) -> dict[str, Any]:
    return {
        "id": f"{scope}{ASSIGNMENTS}/{name}",
        "properties": {"principalId": principal, "roleDefinitionId": definition, "scope": scope},
    }


def _definition(name: str, actions: list[str], data_actions: list[str] | None = None) -> dict:
    return {
        "properties": {
            "roleName": name,
            "permissions": [{"actions": actions, "dataActions": data_actions or []}],
        }
    }


def _responses(**overrides: object) -> dict[str, object]:
    responses: dict[str, object] = {
        f"{ROOT}/descendants": {
            "value": [
                {"name": "platform", "type": "Microsoft.Management/managementGroups"},
                {"name": "sub-1", "type": "Microsoft.Management/managementGroups/subscriptions"},
            ]
        },
        f"{ROOT}{ASSIGNMENTS}": {"value": []},
        f"{CHILD}{ASSIGNMENTS}": {
            "value": [_assignment("mg-owner", "principal-a", OWNER, CHILD)],
        },
        f"{SUB}{ASSIGNMENTS}": {
            "value": [
                # Inherited rows can repeat; each assignment counts once.
                _assignment("mg-owner", "principal-a", OWNER, CHILD),
                _assignment("rg-wildcard", "principal-b", WILDCARD, f"{SUB}/resourceGroups/rg-1"),
                _assignment(
                    "vault-reader",
                    "principal-b",
                    READER,
                    f"{SUB}/resourceGroups/rg-1/providers/Microsoft.KeyVault/vaults/kv1",
                ),
            ]
        },
        OWNER: _definition("Owner", ["*"]),
        WILDCARD: _definition("Custom wildcard", ["Microsoft.Storage/*"], ["*"]),
        READER: _definition("Reader", ["*/read"]),
    }
    responses.update(overrides)
    return responses


def _client(responses: dict[str, object], requested: list[str]) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        body = responses.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"error": {"code": "NotFound"}})
        if isinstance(body, int):
            return httpx.Response(body, json={"error": {"code": "AuthorizationFailed"}})
        return httpx.Response(200, content=json.dumps(body).encode())

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


def _identity_record(name: str, principal: str) -> ResourceRecord:
    ref = (
        f"{SUB}/resourceGroups/rg-1/providers/Microsoft.ManagedIdentity/"
        f"userAssignedIdentities/{name}"
    )
    return ResourceRecord(
        resource_id=ref.casefold(),
        type="managed-identity",
        props={"properties": {"principalId": principal, "tenantId": TENANT}},
        provider_ref=ref,
    )


async def _hydrate(responses: dict[str, object], requested: list[str]) -> list[ResourceRecord]:
    async with _client(responses, requested) as client:
        hydrator = ArmRulePropertyHydrator(
            identity=_Identity(),
            http_client=client,
            arm_endpoint=ARM,
            audience="https://management.azure.com/.default",
            timeout_seconds=5,
            max_response_bytes=1_000_000,
            max_attempts=1,
            max_reads=100,
        )
        result = await hydrator.hydrate(
            ResourceQueryResult(
                resources=(
                    _identity_record("a", "principal-a"),
                    _identity_record("b", "principal-b"),
                    _identity_record("c", "principal-c"),
                ),
            )
        )
    return list(result.resources)


@pytest.mark.asyncio
async def test_complete_tenant_read_projects_every_identity_scope_and_permission() -> None:
    requested: list[str] = []

    a, b, c = await _hydrate(_responses(), requested)

    assert a.props["role_assignments"] == [
        {"role_name": "Owner", "scope": "subscription", "actions": ["*"], "data_actions": []}
    ]
    assert b.props["role_assignments"] == [
        {
            "role_name": "Reader",
            "scope": "resource",
            "actions": ["*/read"],
            "data_actions": [],
        },
        {
            "role_name": "Custom wildcard",
            "scope": "resource_group",
            "actions": ["Microsoft.Storage/*"],
            "data_actions": ["*"],
        },
    ]
    assert c.props["role_assignments"] == []
    # The tenant hierarchy is read once for every identity in the result.
    assert requested.count(f"{ROOT}/descendants") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {f"{ROOT}/descendants": 403},
        {f"{CHILD}{ASSIGNMENTS}": 403},
        {f"{SUB}{ASSIGNMENTS}": 403},
        {WILDCARD: 403},
        {f"{ROOT}/descendants": {"value": [{"name": "x", "type": "Microsoft.Other/things"}]}},
        {
            f"{SUB}{ASSIGNMENTS}": {
                "value": [_assignment("odd", "principal-a", OWNER, "/unexpected/scope")]
            }
        },
        {
            f"{SUB}{ASSIGNMENTS}": {
                "value": [],
                "nextLink": "https://elsewhere.example/next",
            }
        },
    ],
)
async def test_any_incomplete_tenant_read_leaves_every_identity_unobserved(
    overrides: dict[str, object],
) -> None:
    resources = await _hydrate(_responses(**overrides), [])

    assert all("role_assignments" not in item.props for item in resources)


@pytest.mark.asyncio
async def test_identity_without_principal_or_tenant_is_not_read() -> None:
    requested: list[str] = []
    record = ResourceRecord(
        resource_id="identity-without-principal",
        type="managed-identity",
        props={"properties": {"tenantId": TENANT}},
    )
    async with _client(_responses(), requested) as client:
        hydrator = ArmRulePropertyHydrator(
            identity=_Identity(),
            http_client=client,
            arm_endpoint=ARM,
            audience="https://management.azure.com/.default",
            timeout_seconds=5,
            max_response_bytes=1_000_000,
            max_attempts=1,
            max_reads=100,
        )
        result = await hydrator.hydrate(ResourceQueryResult(resources=(record,)))

    assert "role_assignments" not in result.resources[0].props
    assert requested == []
