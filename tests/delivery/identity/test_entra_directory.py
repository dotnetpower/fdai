from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from fdai.delivery.identity import EntraHumanIdentityDirectory
from fdai.shared.providers.workload_identity import IdentityToken


class FakeIdentity:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token="graph-token",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            audience=audience,
        )


async def test_entra_directory_searches_graph_and_normalizes_users() -> None:
    identity = FakeIdentity()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer graph-token"
        assert request.headers["consistencylevel"] == "eventual"
        assert request.url.params["$top"] == "10"
        assert "O''Neil" in request.url.params["$filter"]
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "entra-user-1",
                        "displayName": "O'Neil Kim",
                        "userPrincipalName": "oneil@example.com",
                        "mail": "oneil@example.com",
                        "userType": "Member",
                        "accountEnabled": True,
                    },
                    {
                        "id": "entra-user-2",
                        "displayName": "Disabled User",
                        "userPrincipalName": "disabled@example.com",
                        "userType": "Guest",
                        "accountEnabled": False,
                    },
                    {"id": "missing-display-name"},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        directory = EntraHumanIdentityDirectory(client=client, identity=identity)
        users = await directory.search("O'Neil", limit=10)

    assert identity.audiences == ["https://graph.microsoft.com/.default"]
    assert [user.to_dict() for user in users] == [
        {
            "provider": "entra",
            "subject_id": "entra-user-1",
            "username": "oneil@example.com",
            "display_name": "O'Neil Kim",
            "user_type": "member",
            "active": True,
        },
        {
            "provider": "entra",
            "subject_id": "entra-user-2",
            "username": "disabled@example.com",
            "display_name": "Disabled User",
            "user_type": "guest",
            "active": False,
        },
    ]


async def test_entra_directory_rejects_invalid_search_before_token_request() -> None:
    identity = FakeIdentity()
    async with httpx.AsyncClient() as client:
        directory = EntraHumanIdentityDirectory(client=client, identity=identity)
        for query, limit in (("x", 20), ("valid", 0), ("valid", 51)):
            try:
                await directory.search(query, limit=limit)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid search input was accepted")
    assert identity.audiences == []


async def test_entra_directory_gets_exact_subject_and_handles_not_found() -> None:
    identity = FakeIdentity()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/users/user-1":
            return httpx.Response(
                200,
                json={
                    "id": "user-1",
                    "displayName": "Alex Kim",
                    "userPrincipalName": "alex@example.com",
                    "accountEnabled": True,
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        directory = EntraHumanIdentityDirectory(client=client, identity=identity)
        found = await directory.get_by_subject_id("user-1")
        missing = await directory.get_by_subject_id("missing")

    assert found is not None
    assert found.username == "alex@example.com"
    assert missing is None


async def test_entra_directory_builds_group_and_people_role_roster() -> None:
    identity = FakeIdentity()

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1.0/groups/group-reader":
            return httpx.Response(200, json={"id": "group-reader", "displayName": "fdai-readers"})
        if path == "/v1.0/groups/group-owner":
            return httpx.Response(200, json={"id": "group-owner", "displayName": "fdai-owners"})
        if path.endswith("/transitiveMembers/microsoft.graph.user"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "user-1",
                            "displayName": "Alex Kim",
                            "userPrincipalName": "alex@example.com",
                            "accountEnabled": True,
                        }
                    ]
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        directory = EntraHumanIdentityDirectory(client=client, identity=identity)
        roster = await directory.list_role_roster(
            {"Reader": "group-reader", "Owner": "group-owner"}
        )

    assert [(item.principal_type, item.display_name) for item in roster] == [
        ("group", "fdai-readers"),
        ("group", "fdai-owners"),
        ("person", "Alex Kim"),
    ]
    assert roster[-1].roles == ("Reader", "Owner")


async def test_entra_directory_discovers_application_role_roster() -> None:
    identity = FakeIdentity()
    service_principal_requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal service_principal_requests
        path = request.url.path
        if path == "/v1.0/servicePrincipals":
            service_principal_requests += 1
            assert request.url.params["$filter"] == "appId eq 'api-app-id'"
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "api-service-principal",
                            "appRoles": [
                                {"id": "reader-role", "value": "Reader"},
                                {"id": "owner-role", "value": "Owner"},
                            ],
                        }
                    ],
                },
            )
        if path == "/v1.0/servicePrincipals/api-service-principal/appRoleAssignedTo":
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "appRoleId": "reader-role",
                            "principalId": "reader-group",
                            "principalType": "Group",
                        },
                        {
                            "appRoleId": "owner-role",
                            "principalId": "owner-user",
                            "principalType": "User",
                        },
                    ],
                },
            )
        if path == "/v1.0/groups/reader-group":
            return httpx.Response(
                200,
                json={"id": "reader-group", "displayName": "fdai-readers-dev"},
            )
        if path.endswith("/transitiveMembers/microsoft.graph.user"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "reader-user",
                            "displayName": "Reader User",
                            "userPrincipalName": "reader@tenant.example",
                            "accountEnabled": True,
                        }
                    ],
                },
            )
        if path == "/v1.0/users/owner-user":
            return httpx.Response(
                200,
                json={
                    "id": "owner-user",
                    "displayName": "Owner User",
                    "userPrincipalName": "owner@tenant.example",
                    "accountEnabled": True,
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        directory = EntraHumanIdentityDirectory(
            client=client,
            identity=identity,
            application_id="api-app-id",
        )
        roster = await directory.list_role_roster({"Reader": "ignored-placeholder"})
        cached_roster = await directory.list_role_roster({"Reader": "ignored-placeholder"})

    assert [(item.display_name, item.roles) for item in roster] == [
        ("fdai-readers-dev", ("Reader",)),
        ("Owner User", ("Owner",)),
        ("Reader User", ("Reader",)),
    ]
    assert cached_roster == roster
    assert service_principal_requests == 1


async def test_entra_directory_rejects_cross_origin_next_link() -> None:
    identity = FakeIdentity()
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1.0/groups/group-reader":
            return httpx.Response(200, json={"id": "group-reader", "displayName": "Readers"})
        if request.url.path.endswith("/transitiveMembers/microsoft.graph.user"):
            return httpx.Response(
                200,
                json={"value": [], "@odata.nextLink": "https://example.com/steal-token"},
            )
        raise AssertionError(f"unexpected request: {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        directory = EntraHumanIdentityDirectory(client=client, identity=identity)
        try:
            await directory.list_role_roster({"Reader": "group-reader"})
        except RuntimeError as exc:
            assert "outside" in str(exc)
        else:
            raise AssertionError("cross-origin nextLink was accepted")

    assert all(request.url.host == "graph.microsoft.com" for request in requests)
