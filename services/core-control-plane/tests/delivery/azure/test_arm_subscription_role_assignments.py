"""Subscription role assignments are projected completely, including group guests, or not at all."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fdai.delivery.azure.arm_rule_property_hydration import (
    GRAPH_AUDIENCE,
    ArmRulePropertyHydrator,
)
from fdai.delivery.azure.inventory import ResourceQueryResult
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.workload_identity import IdentityToken

SUB = "sub-1"
ARM = "https://management.azure.com"
GRAPH = "https://graph.microsoft.com"
ASSIGNMENTS = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleAssignments"
PIM = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleAssignmentScheduleInstances"
OWNER = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions/owner"
READER = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions/reader"


class _Identity:
    def __init__(self, *, graph: bool = True) -> None:
        self.graph = graph

    async def get_token(self, audience: str) -> IdentityToken:
        if audience == GRAPH_AUDIENCE and not self.graph:
            raise ValueError("graph token unavailable")
        return IdentityToken(
            token="test-token",  # noqa: S106 - deterministic test credential
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            audience=audience,
        )


def _assignment(name: str, principal: str, kind: str, definition: str) -> dict[str, Any]:
    return {
        "id": f"{ASSIGNMENTS}/{name}",
        "properties": {
            "principalId": principal,
            "principalType": kind,
            "roleDefinitionId": definition,
            "scope": f"/subscriptions/{SUB}",
        },
    }


def _transport(*, pim: str = "license", guest_group: bool = True, user_type: str = "Guest"):  # noqa: ANN202
    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        path = request.url.path
        if path == ASSIGNMENTS:
            return httpx.Response(
                200,
                json={
                    "value": [
                        _assignment("a1", "user-1", "User", OWNER),
                        _assignment("a2", "group-1", "Group", READER),
                        _assignment("a3", "sp-1", "ServicePrincipal", OWNER),
                    ]
                },
            )
        if path == PIM:
            if pim == "license":
                return httpx.Response(400, json={"error": {"code": "AadPremiumLicenseRequired"}})
            if pim == "error":
                return httpx.Response(403, json={"error": {"code": "AuthorizationFailed"}})
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "properties": {
                                "originRoleAssignmentId": f"{ASSIGNMENTS}/a1",
                                "assignmentType": "Activated",
                            }
                        }
                    ]
                },
            )
        if path == OWNER:
            return httpx.Response(200, json={"properties": {"roleName": "Owner"}})
        if path == READER:
            return httpx.Response(200, json={"properties": {"roleName": "Reader"}})
        if url.startswith(f"{GRAPH}/v1.0/users/user-1"):
            return httpx.Response(200, json={"userType": user_type})
        if url.startswith(f"{GRAPH}/v1.0/groups/group-1/transitiveMembers"):
            members = [{"userType": "Member"}]
            if guest_group:
                members.append({"userType": "Guest"})
            return httpx.Response(200, json={"value": members})
        return httpx.Response(404, json={"error": {"code": "NotFound"}})

    return httpx.MockTransport(handle)


def _subscription() -> ResourceRecord:
    return ResourceRecord(
        resource_id="subscription-1",
        type="subscription",
        props={"subscriptionId": SUB, "providerType": "microsoft.resources/subscriptions"},
        provider_ref=f"/subscriptions/{SUB}",
    )


async def _hydrate(**options: Any) -> dict[str, Any]:
    identity = _Identity(graph=options.pop("graph", True))
    async with httpx.AsyncClient(transport=_transport(**options)) as client:
        result = await ArmRulePropertyHydrator(
            identity=identity,  # type: ignore[arg-type]
            http_client=client,
            arm_endpoint=ARM,
            audience="https://management.azure.com/.default",
            timeout_seconds=5.0,
            max_response_bytes=1_000_000,
            max_attempts=1,
            max_reads=50,
        ).hydrate(ResourceQueryResult(resources=(_subscription(),)))
    return dict(result.resources[0].props)


@pytest.mark.asyncio
async def test_without_pim_license_every_assignment_is_standing_and_group_guests_surface() -> None:
    props = await _hydrate()

    assert [
        (item["role_name"], item["principal_type"], item["standing"])
        for item in props["role_assignments"]
    ] == [
        ("Owner", "Guest", True),
        ("Owner", "ServicePrincipal", True),
        ("Reader", "Group", True),
        ("Reader", "Guest", True),
    ]
    assert {item["scope"] for item in props["role_assignments"]} == {"subscription"}


@pytest.mark.asyncio
async def test_pim_activation_marks_just_in_time_access_as_not_standing() -> None:
    props = await _hydrate(pim="ok", user_type="Member", guest_group=False)

    owner_user = next(
        item
        for item in props["role_assignments"]
        if item["role_name"] == "Owner" and item["principal_type"] == "User"
    )
    assert owner_user["standing"] is False
    assert all(item["principal_type"] != "Guest" for item in props["role_assignments"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options",
    [{"pim": "error"}, {"graph": False}, {"user_type": "Unknown"}],
    ids=["pim-denied", "graph-token", "user-type"],
)
async def test_any_incomplete_read_leaves_assignments_unobserved(options: dict[str, Any]) -> None:
    props = await _hydrate(**options)

    assert "role_assignments" not in props
