"""Managed-identity role assignments are projected completely or not at all."""

from __future__ import annotations

import httpx
from fdai.delivery.azure.arm_role_assignment_hydration import scope_kind
from fdai.delivery.azure.arm_rule_property_hydration import ArmRulePropertyHydrator
from fdai.delivery.azure.inventory import ResourceQueryResult
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

SUB = "sub-1"
ASSIGNMENTS = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleAssignments"
OWNER = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions/owner"
READER = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions/reader"


def _identity_resource(name: str, principal: str) -> ResourceRecord:
    return ResourceRecord(
        resource_id=name,
        type="managed-identity",
        props={"subscriptionId": SUB, "properties": {"principalId": principal}},
        provider_ref=f"/subscriptions/{SUB}/resourceGroups/rg/providers/x/{name}",
    )


def _assignment(principal: str, definition: str, scope: str) -> dict[str, object]:
    return {
        "properties": {
            "principalId": principal,
            "principalType": "ServicePrincipal",
            "roleDefinitionId": definition,
            "scope": scope,
        }
    }


def _transport(*, fail_definition: bool = False) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == ASSIGNMENTS and "page=2" not in str(request.url):
            return httpx.Response(
                200,
                json={
                    "value": [_assignment("P-ONE", OWNER, f"/subscriptions/{SUB}")],
                    "nextLink": f"https://management.azure.com{ASSIGNMENTS}?page=2",
                },
            )
        if path == ASSIGNMENTS:
            return httpx.Response(
                200,
                json={
                    "value": [
                        _assignment("p-one", READER, f"/subscriptions/{SUB}/resourceGroups/rg"),
                        _assignment(
                            "p-two",
                            OWNER,
                            "/providers/Microsoft.Management/managementGroups/root",
                        ),
                    ]
                },
            )
        if path == OWNER:
            if fail_definition:
                return httpx.Response(500, json={})
            return httpx.Response(
                200,
                json={
                    "properties": {
                        "roleName": "Owner",
                        "permissions": [{"actions": ["*"], "notActions": []}],
                    }
                },
            )
        if path == READER:
            return httpx.Response(
                200,
                json={
                    "properties": {"roleName": "Reader", "permissions": [{"actions": ["*/read"]}]}
                },
            )
        return httpx.Response(404, json={})

    return httpx.MockTransport(handle)


def _hydrator(client: httpx.AsyncClient) -> ArmRulePropertyHydrator:
    return ArmRulePropertyHydrator(
        identity=StaticWorkloadIdentity(
            audience="https://management.azure.com/.default",
            token="test-token",  # noqa: S106 - deterministic test credential
        ),
        http_client=client,
        arm_endpoint="https://management.azure.com",
        audience="https://management.azure.com/.default",
        timeout_seconds=5.0,
        max_response_bytes=1_000_000,
        max_attempts=1,
        max_reads=20,
    )


async def test_identities_receive_every_assignment_that_applies_to_them() -> None:
    resources = (
        _identity_resource("one", "p-one"),
        _identity_resource("two", "P-TWO"),
        _identity_resource("three", "p-three"),
    )
    async with httpx.AsyncClient(transport=_transport()) as client:
        result = await _hydrator(client).hydrate(ResourceQueryResult(resources=resources))

    by_name = {item.resource_id: item.props.get("role_assignments") for item in result.resources}
    assert by_name["one"] == [
        {
            "scope": "resource_group",
            "role_name": "Reader",
            "actions": ["*/read"],
            "data_actions": [],
            "principal_type": "ServicePrincipal",
        },
        {
            "scope": "subscription",
            "role_name": "Owner",
            "actions": ["*"],
            "data_actions": [],
            "principal_type": "ServicePrincipal",
        },
    ]
    # A management-group assignment covers the whole subscription.
    assert by_name["two"] is not None and by_name["two"][0]["scope"] == "subscription"
    assert by_name["three"] == []


async def test_any_failed_read_leaves_the_subscription_unobserved() -> None:
    resources = (_identity_resource("one", "p-one"),)
    async with httpx.AsyncClient(transport=_transport(fail_definition=True)) as client:
        result = await _hydrator(client).hydrate(ResourceQueryResult(resources=resources))

    assert "role_assignments" not in result.resources[0].props


def test_scope_kinds() -> None:
    assert scope_kind(f"/subscriptions/{SUB}", SUB) == "subscription"
    assert scope_kind("/", SUB) == "subscription"
    assert scope_kind(f"/subscriptions/{SUB}/resourceGroups/rg", SUB) == "resource_group"
    assert scope_kind(f"/subscriptions/{SUB}/resourceGroups/rg/providers/x/y", SUB) == "resource"
