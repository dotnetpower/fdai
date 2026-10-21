from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from azure.core.exceptions import ClientAuthenticationError

from fdai_lifecycle_agent.hub_client import HttpHubClient, HubProtocolError
from fdai_lifecycle_agent.remote_auth import WorkloadIdentityAuthorization


def test_exact_scope_and_token_refresh_for_each_call() -> None:
    credential = Mock()
    credential.get_token.side_effect = [
        SimpleNamespace(token="test-first"),
        SimpleNamespace(token="test-second"),
    ]
    authorization = WorkloadIdentityAuthorization(
        "api://hub-example/.default", connect=lambda: credential
    )
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        return httpx.Response(204)

    with HttpHubClient(
        "https://hub.example.com",
        authorization=authorization,
        transport=httpx.MockTransport(handle),
    ) as client:
        client.fetch_plan("installation-alpha")
        client.fetch_plan("installation-alpha")
    authorization.close()
    assert seen == ["Bearer test-first", "Bearer test-second"]
    assert credential.get_token.call_count == 2
    credential.get_token.assert_called_with("api://hub-example/.default")
    credential.close.assert_called_once()


@pytest.mark.parametrize(
    "scope",
    [
        "",
        "https://management.azure.com/.default",
        "api:///.default",
        "api://hub/read",
        "api://hub/.default?other",
        "api://hub scope/.default",
    ],
)
def test_scope_rejection_precedes_credential_construction(scope: str) -> None:
    connect = Mock()
    with pytest.raises(ValueError):
        WorkloadIdentityAuthorization(scope, connect=connect)
    connect.assert_not_called()


@pytest.mark.parametrize(
    "error", [ClientAuthenticationError(message="private diagnostic"), OSError("private path")]
)
def test_credential_failures_are_sanitized_and_not_retried(error: Exception) -> None:
    credential = Mock()
    credential.get_token.side_effect = error
    auth = WorkloadIdentityAuthorization("api://hub/.default", connect=lambda: credential)
    with pytest.raises(HubProtocolError, match="^Hub workload identity authentication failed.$"):
        auth()
    assert credential.get_token.call_count == 1


def test_missing_projected_bindings_never_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_FEDERATED_TOKEN_FILE"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="projected token-file"):
        WorkloadIdentityAuthorization("api://hub/.default")


def test_bearer_cannot_use_plain_http_or_follow_redirect() -> None:
    credential = Mock(return_value="test-only")
    with pytest.raises(ValueError, match="HTTPS"):
        HttpHubClient("http://127.0.0.1", authorization=credential)
    credential.assert_not_called()
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(302, headers={"location": "https://other.example.com"})

    with HttpHubClient(
        "https://hub.example.com",
        authorization=credential,
        transport=httpx.MockTransport(handle),
    ) as client:
        with pytest.raises(HubProtocolError, match="302"):
            client.fetch_plan("installation-alpha")
    assert seen == ["hub.example.com"]
