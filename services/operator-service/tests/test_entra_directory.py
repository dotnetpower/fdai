"""Focused tests for the Operator service Microsoft Graph directory reader."""

from __future__ import annotations

import httpx
import pytest
from fdai_operator_service.entra_directory import EntraHumanIdentityDirectory
from fdai_operator_service.families.iam.errors import IamUnavailableError


async def _token(_: str) -> str:
    return "token"


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_provider_failures_are_explicit_iam_unavailability(status: int) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(status))
    ) as client:
        directory = EntraHumanIdentityDirectory(
            client=client, token_provider=_token, max_attempts=1
        )
        with pytest.raises(IamUnavailableError, match=f"HTTP {status}") as captured:
            await directory.get_by_subject_id("example-user")
    assert "example-user" not in str(captured.value)
    assert "graph.microsoft.com" not in str(captured.value)
    assert (await directory.directory_status()).availability == "unavailable"


async def test_directory_transport_failure_is_explicit_iam_unavailability() -> None:
    def failed(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(failed)) as client:
        directory = EntraHumanIdentityDirectory(client=client, token_provider=_token)
        with pytest.raises(IamUnavailableError, match="directory connection is unavailable"):
            await directory.get_by_subject_id("example-user")
    assert (await directory.directory_status()).availability == "unavailable"


@pytest.mark.parametrize("kind", ["user", "group"])
async def test_absent_directory_subject_still_returns_none(kind: str) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(404))
    ) as client:
        directory = EntraHumanIdentityDirectory(client=client, token_provider=_token)
        assert await directory.get_steward_subject_by_id("example-subject", kind=kind) is None


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
                            "userPrincipalName": "user-login@example.com",
                            "mail": "user@example.com",
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
    assert users[0].username == "user@example.com"
    assert users[0].user_type == "member"
    assert [item.principal_type for item in roster] == ["group", "person"]
    assert roster[1].roles == ("Reader",)
    assert roster[1].group_ids == ("readers",)
    assert "group_ids" not in roster[1].to_dict()
    assert users[0].group_ids == ()
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
    assert roster[0].group_ids == ()


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
        group_as_user = await directory.get_by_subject_id("group-1")
        group = await directory.get_steward_subject_by_id("group-1", kind="group")

    assert user is not None
    assert user.principal_type == "person"
    assert group_as_user is None
    assert group is not None
    assert group.principal_type == "group"
    assert group.display_name == "Example Operations"


@pytest.mark.parametrize("group_first", [False, True])
async def test_group_membership_survives_direct_role_merge_but_not_a_later_removal(group_first):
    include_group = True
    person = {
        "id": "user-1",
        "displayName": "Example User",
        "mail": "user@example.com",
        "accountEnabled": True,
        "userType": "Member",
    }

    def handler(request):
        path = request.url.path
        assert request.method == "GET"
        if path.endswith("/servicePrincipals"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "app-1",
                            "appRoles": [
                                {"id": "role-reader", "value": "Reader"},
                                {"id": "role-owner", "value": "Owner"},
                            ],
                        }
                    ]
                },
            )
        if path.endswith("/appRoleAssignedTo"):
            assignments = [
                {"appRoleId": "role-owner", "principalId": "user-1", "principalType": "User"}
            ]
            if include_group:
                assignments.append(
                    {"appRoleId": "role-reader", "principalId": "readers", "principalType": "Group"}
                )
            return httpx.Response(
                200, json={"value": assignments[::-1] if group_first else assignments}
            )
        if path.endswith("/groups/readers"):
            return httpx.Response(200, json={"id": "readers", "displayName": "Example Readers"})
        if path.endswith("/microsoft.graph.user"):
            return httpx.Response(200, json={"value": [person]})
        if path.endswith("/users/user-1"):
            return httpx.Response(200, json=person)
        raise AssertionError(path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        directory = EntraHumanIdentityDirectory(client, _token, application_id="app-1")
        roster = await directory.list_role_roster({}, limit=50)
        identity = next(item for item in roster if item.principal_type == "person")
        assert identity.group_ids == ("readers",)
        assert identity.roles == ("Owner", "Reader")
        include_group = False
        fresh = await directory.list_role_roster({}, limit=50)
        assert fresh[0].group_ids == ()
        assert fresh[0].roles == ("Owner",)
