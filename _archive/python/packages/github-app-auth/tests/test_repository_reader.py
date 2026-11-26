from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fdai_github_app_auth.repository_reader import (
    MAX_RESPONSE_BYTES,
    GitHubApiRepositoryReader,
    GitHubRepositoryReadError,
)

COMMIT = "c" * 40


def response(request: httpx.Request, *, private: bool = False) -> httpx.Response:
    if request.url.path.endswith("/commits/main"):
        return httpx.Response(200, json={"sha": COMMIT})
    if request.url.path.endswith("/readme"):
        assert request.url.params["ref"] == COMMIT
        return httpx.Response(
            200,
            json={
                "type": "file",
                "encoding": "base64",
                "size": 5,
                "content": base64.b64encode(b"hello").decode(),
            },
        )
    return httpx.Response(
        200,
        json={
            "id": 123,
            "full_name": "example/app",
            "private": private,
            "default_branch": "main",
        },
    )


async def test_anonymous_source_reads_exact_commit_and_readme_without_identity() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert "authorization" not in request.headers
        assert request.method == "GET"
        return response(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await GitHubApiRepositoryReader(
            {"FDAI_GITOPS_TOKEN": "unused-compatibility-value"}, client
        ).verify("example/app", "public")
    assert len(calls) == 3
    assert result.commit == COMMIT and result.repository_id == 123
    assert result.readme_digest == hashlib.sha256(b"hello").hexdigest()


async def test_app_uses_existing_provider_with_one_repository_and_read_permissions() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    environment = {
        "FDAI_GITHUB_APP_CLIENT_ID": "Iv1.example",
        "FDAI_GITHUB_APP_INSTALLATION_ID": "123",
        "FDAI_GITHUB_APP_PRIVATE_KEY": pem,
    }
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST":
            assert json.loads(request.content) == {
                "repositories": ["app"],
                "permissions": {"contents": "read", "metadata": "read"},
            }
            return httpx.Response(
                201,
                json={
                    "token": "generated-installation-test-identity",
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                    "permissions": {"contents": "read", "metadata": "read"},
                    "repository_selection": "selected",
                },
            )
        assert request.headers["authorization"].startswith("Bearer ")
        return response(request, private=True)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await GitHubApiRepositoryReader(environment, client).verify(
            "example/app", "deployment-github-app"
        )
    assert result.private is True and len(calls) == 4


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"FDAI_GITHUB_APP_CLIENT_ID": "Iv1.example"},
        {"FDAI_GITOPS_TOKEN": "compatibility"},
    ],
)
async def test_missing_partial_and_static_credentials_do_not_become_app_access(environment) -> None:
    def handler(request):
        pytest.fail("missing identity must stop before GitHub access")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(GitHubRepositoryReadError):
            await GitHubApiRepositoryReader(environment, client).verify(
                "example/app", "deployment-github-app"
            )


@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 503])
async def test_read_failure_is_sanitized_and_not_retried(status) -> None:
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, text="untrusted provider details", headers={"location": "https://example.com"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(GitHubRepositoryReadError) as failure:
            await GitHubApiRepositoryReader({}, client).verify("example/app", "public")
    assert len(calls) == 1 and "untrusted" not in str(failure.value)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"id": True},
        {"id": 1, "full_name": 1},
        {"id": 1, "full_name": "example/other", "private": False, "default_branch": "main"},
        {"id": 1, "full_name": "example/app", "private": True, "default_branch": "main"},
        {"id": 1, "full_name": "example/app", "private": "false", "default_branch": "main"},
    ],
)
async def test_malformed_or_private_anonymous_metadata_is_rejected(payload) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(GitHubRepositoryReadError):
            await GitHubApiRepositoryReader({}, client).verify("example/app", "public")


@pytest.mark.parametrize(
    "location", ["example/..", "example/.", "example/app/extra", "https://example.com/app"]
)
async def test_invalid_location_never_reaches_provider(location) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: pytest.fail("unexpected read"))
    ) as client:
        with pytest.raises(GitHubRepositoryReadError):
            await GitHubApiRepositoryReader({}, client).verify(location, "public")


async def test_oversize_json_and_timeout_fail_closed() -> None:
    for handler in (
        lambda request: httpx.Response(200, content=b" " * (MAX_RESPONSE_BYTES + 1)),
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("provider details")),
    ):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(GitHubRepositoryReadError):
                await GitHubApiRepositoryReader({}, client).verify("example/app", "public")


@pytest.mark.parametrize(
    "payload",
    [
        {"sha": "not-a-commit"},
        {"type": "file", "encoding": "base64", "size": 5, "content": "invalid%"},
        {"type": "file", "encoding": "base64", "size": 99, "content": "aGVsbG8="},
        {"type": "symlink", "encoding": "base64", "size": 5, "content": "aGVsbG8="},
    ],
)
async def test_commit_or_readme_payload_failure_is_not_a_verified_connection(payload) -> None:
    def handler(request):
        if request.url.path.endswith("/commits/main") and "sha" in payload:
            return httpx.Response(200, json=payload)
        if request.url.path.endswith("/readme"):
            return httpx.Response(200, json=payload)
        return response(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(GitHubRepositoryReadError):
            await GitHubApiRepositoryReader({}, client).verify("example/app", "public")
