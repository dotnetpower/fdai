from __future__ import annotations

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fdai.agents import StateStoreIssueTrackerAdapter
from fdai.delivery.github_issue_tracker import GitHubAppIssueTrackerAdapter
from fdai.runtime.bootstrap_saga_issue_tracker import build_saga_issue_tracker
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _private_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


async def test_saga_github_bootstrap_requires_exact_app_repository_projection() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/app/installations/123/access_tokens":
            return httpx.Response(
                201,
                json={
                    "token": "installation-token",
                    "expires_at": "2099-01-01T00:00:00Z",
                    "repository_selection": "selected",
                    "permissions": {"issues": "write", "metadata": "read"},
                },
            )
        if request.url.path == "/installation/repositories":
            return httpx.Response(
                200,
                json={"repositories": [{"id": 7, "name": "fdai", "full_name": "example/fdai"}]},
            )
        return httpx.Response(404, json={})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        adapter = await build_saga_issue_tracker(
            environment={
                "FDAI_SAGA_GITHUB_ISSUES_ENABLED": "true",
                "FDAI_SAGA_GITHUB_OWNER": "example",
                "FDAI_SAGA_GITHUB_REPO": "fdai",
                "FDAI_GITHUB_APP_CLIENT_ID": "Iv1.example",
                "FDAI_GITHUB_APP_INSTALLATION_ID": "123",
                "FDAI_GITHUB_APP_PRIVATE_KEY": _private_key(),
            },
            store=InMemoryStateStore(),
            http_client=http,
        )
    finally:
        await http.aclose()

    assert isinstance(adapter, GitHubAppIssueTrackerAdapter)
    assert [request.url.path for request in requests] == [
        "/app/installations/123/access_tokens",
        "/installation/repositories",
    ]


async def test_saga_github_bootstrap_defaults_local_and_rejects_static_tokens() -> None:
    store = InMemoryStateStore()
    local = await build_saga_issue_tracker(
        environment={},
        store=store,
        http_client=None,
    )
    assert isinstance(local, StateStoreIssueTrackerAdapter)

    async with httpx.AsyncClient() as http:
        with pytest.raises(RuntimeError, match="refreshable GitHub App"):
            await build_saga_issue_tracker(
                environment={
                    "FDAI_SAGA_GITHUB_ISSUES_ENABLED": "true",
                    "FDAI_SAGA_GITHUB_OWNER": "example",
                    "FDAI_SAGA_GITHUB_REPO": "fdai",
                    "FDAI_GITOPS_TOKEN": "static-token",
                },
                store=store,
                http_client=http,
            )
