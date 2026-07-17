"""Graph stewardship adapter tests (httpx MockTransport, no network)."""

from __future__ import annotations

import httpx
import pytest

from fdai.core.stewardship.model import StewardKind
from fdai.delivery.stewardship import (
    GraphGroupMembershipProvider,
    GraphIdentityDirectory,
    GraphPersonDirectory,
)


async def _token() -> str:
    return "test-token"


async def test_person_directory_resolves_one_exact_active_user() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/users"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "00000000-0000-0000-0000-000000000101",
                            "displayName": "Example Operator",
                            "accountEnabled": True,
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"value": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        directory = GraphPersonDirectory(client=client, token_provider=_token)
        identity = await directory.resolve("Example Operator")

    assert identity is not None
    assert identity.kind is StewardKind.USER


async def test_person_directory_resolves_group_and_abstains_on_ambiguity() -> None:
    ambiguous = False

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/users"):
            values = (
                [{"id": "user-1", "displayName": "Operations", "accountEnabled": True}]
                if ambiguous
                else []
            )
            return httpx.Response(200, json={"value": values})
        return httpx.Response(
            200,
            json={"value": [{"id": "group-1", "displayName": "Operations"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        directory = GraphPersonDirectory(client=client, token_provider=_token)
        resolved = await directory.resolve("Operations")
        ambiguous = True
        unresolved = await directory.resolve("Operations")

    assert resolved is not None and resolved.kind is StewardKind.GROUP
    assert unresolved is None


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_is_active_true_when_account_enabled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json={"accountEnabled": True})

    async with _client(handler) as client:
        directory = GraphIdentityDirectory(client=client, token_provider=_token)
        assert await directory.is_active("oid-1") is True


async def test_is_active_false_when_disabled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"accountEnabled": False})

    async with _client(handler) as client:
        directory = GraphIdentityDirectory(client=client, token_provider=_token)
        assert await directory.is_active("oid-1") is False


async def test_is_active_false_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"code": "Request_ResourceNotFound"}})

    async with _client(handler) as client:
        directory = GraphIdentityDirectory(client=client, token_provider=_token)
        assert await directory.is_active("missing") is False


async def test_is_active_raises_on_server_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with _client(handler) as client:
        directory = GraphIdentityDirectory(client=client, token_provider=_token)
        with pytest.raises(httpx.HTTPStatusError):
            await directory.is_active("oid-1")


async def test_members_of_follows_pagination() -> None:
    page1 = {
        "value": [{"id": "u1"}, {"id": "u2"}],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/groups/g/members?page=2",
    }
    page2 = {"value": [{"id": "u3"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if "page=2" in str(request.url):
            return httpx.Response(200, json=page2)
        return httpx.Response(200, json=page1)

    async with _client(handler) as client:
        provider = GraphGroupMembershipProvider(client=client, token_provider=_token)
        members = await provider.members_of("g")
        assert members == ("u1", "u2", "u3")


async def test_members_of_unknown_group_returns_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async with _client(handler) as client:
        provider = GraphGroupMembershipProvider(client=client, token_provider=_token)
        assert await provider.members_of("missing") == ()
