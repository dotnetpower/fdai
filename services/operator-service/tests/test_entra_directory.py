"""Focused tests for the Operator service Microsoft Graph directory reader."""

from __future__ import annotations

import httpx
import pytest
from fdai_operator_service.entra_directory import EntraHumanIdentityDirectory


async def _token(_: str) -> str:
    return "token"


async def test_search_and_roster_project_only_bounded_identity_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("Bearer ")
        if request.url.path.endswith("/users") and "$filter" in request.url.params:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "user-1",
                            "displayName": "Example User",
                            "userPrincipalName": "user@example.com",
                            "userType": "Member",
                            "accountEnabled": True,
                        }
                    ]
                },
            )
        if request.url.path.endswith("/groups/readers"):
            return httpx.Response(200, json={"id": "readers", "displayName": "FDAI Readers"})
        if request.url.path.endswith("/microsoft.graph.user"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "user-1",
                            "displayName": "Example User",
                            "userPrincipalName": "user@example.com",
                            "userType": "Member",
                            "accountEnabled": True,
                        }
                    ]
                },
            )
        raise AssertionError(request.url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        directory = EntraHumanIdentityDirectory(client=client, token_provider=_token)
        users = await directory.search("Exam", limit=20)
        roster = await directory.list_role_roster({"Reader": "readers"}, limit=50)
        status = await directory.directory_status()

    assert users[0].subject_id == "user-1"
    assert users[0].user_type == "member"
    assert [item.principal_type for item in roster] == ["group", "person"]
    assert roster[1].roles == ("Reader",)
    assert status.source == "microsoft-graph"
    assert status.availability == "available"
    assert status.observed_at is not None


async def test_directory_rejects_cross_origin_pagination() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/groups/readers"):
            return httpx.Response(200, json={"id": "readers", "displayName": "FDAI Readers"})
        return httpx.Response(
            200,
            json={"value": [], "@odata.nextLink": "https://example.com/v1.0/users"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        directory = EntraHumanIdentityDirectory(client=client, token_provider=_token)
        with pytest.raises(RuntimeError, match="left the configured API"):
            await directory.list_role_roster({"Reader": "readers"}, limit=50)

    assert (await directory.directory_status()).availability == "unavailable"


async def test_application_role_roster_ignores_placeholder_group_configuration() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/servicePrincipals"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "service-principal-1",
                            "appRoles": [{"id": "role-1", "value": "Owner"}],
                        }
                    ]
                },
            )
        if request.url.path.endswith("/appRoleAssignedTo"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "appRoleId": "role-1",
                            "principalId": "user-1",
                            "principalType": "User",
                        }
                    ]
                },
            )
        if request.url.path.endswith("/users/user-1"):
            return httpx.Response(
                200,
                json={
                    "id": "user-1",
                    "displayName": "Example Owner",
                    "userPrincipalName": "owner@example.com",
                    "userType": "Member",
                    "accountEnabled": True,
                },
            )
        raise AssertionError(request.url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        directory = EntraHumanIdentityDirectory(
            client=client,
            token_provider=_token,
            application_id="application-1",
        )
        roster = await directory.list_role_roster(
            {"Owner": "local-placeholder-owner-group"},
            limit=50,
        )

    assert len(roster) == 1
    assert roster[0].subject_id == "user-1"
    assert roster[0].roles == ("Owner",)


async def test_exact_subject_lookup_resolves_users_and_groups() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/users/user-1"):
            return httpx.Response(
                200,
                json={
                    "id": "user-1",
                    "displayName": "Example User",
                    "userPrincipalName": "user@example.com",
                    "userType": "Member",
                    "accountEnabled": True,
                },
            )
        if request.url.path.endswith("/users/group-1"):
            return httpx.Response(404)
        if request.url.path.endswith("/groups/group-1"):
            return httpx.Response(
                200,
                json={"id": "group-1", "displayName": "Example Operations"},
            )
        raise AssertionError(request.url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        directory = EntraHumanIdentityDirectory(client=client, token_provider=_token)
        user = await directory.get_by_subject_id("user-1")
        group = await directory.get_by_subject_id("group-1")

    assert user is not None
    assert user.principal_type == "person"
    assert group is not None
    assert group.principal_type == "group"
    assert group.display_name == "Example Operations"
