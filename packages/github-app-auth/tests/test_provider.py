from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from fdai_github_app_auth import (
    GitHubAppTokenConfig,
    GitHubAppTokenError,
    GitHubAppTokenProvider,
    github_credentials_configured,
)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _private_key() -> tuple[str, rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    encoded = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return encoded.decode(), key


def _config(private_key: str) -> GitHubAppTokenConfig:
    return GitHubAppTokenConfig(
        client_id="Iv1.example",
        installation_id=123,
        private_key_pem=private_key,
        repository="deployment-config",
    )


def test_environment_predicate_accepts_one_complete_credential_mode() -> None:
    assert github_credentials_configured({}) is False
    assert github_credentials_configured({"FDAI_GITOPS_TOKEN": "token"}) is True
    assert (
        github_credentials_configured(
            {
                "FDAI_GITHUB_APP_CLIENT_ID": "Iv1.example",
                "FDAI_GITHUB_APP_INSTALLATION_ID": "123",
                "FDAI_GITHUB_APP_PRIVATE_KEY": "key",
            }
        )
        is True
    )
    with pytest.raises(GitHubAppTokenError, match="incomplete"):
        github_credentials_configured({"FDAI_GITHUB_APP_CLIENT_ID": "Iv1.example"})
    with pytest.raises(GitHubAppTokenError, match="mutually exclusive"):
        github_credentials_configured(
            {
                "FDAI_GITOPS_TOKEN": "token",
                "FDAI_GITHUB_APP_CLIENT_ID": "Iv1.example",
                "FDAI_GITHUB_APP_INSTALLATION_ID": "123",
                "FDAI_GITHUB_APP_PRIVATE_KEY": "key",
            }
        )


async def test_provider_serializes_refresh_and_scopes_token_request() -> None:
    private_key, key = _private_key()
    clock = MutableClock(datetime(2026, 9, 6, tzinfo=UTC))
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        app_jwt = request.headers["Authorization"].split(" ", 1)[1]
        claims = jwt.decode(
            app_jwt,
            key.public_key(),
            algorithms=["RS256"],
            options={"verify_aud": False, "verify_exp": False, "verify_iat": False},
        )
        assert claims["iss"] == "Iv1.example"
        assert claims["iat"] == int((clock.value - timedelta(seconds=60)).timestamp())
        assert claims["exp"] == int((clock.value + timedelta(minutes=9)).timestamp())
        assert request.url.path == "/app/installations/123/access_tokens"
        assert json.loads(request.content) == {
            "repositories": ["deployment-config"],
            "permissions": {
                "contents": "write",
                "issues": "write",
                "metadata": "read",
                "pull_requests": "write",
            },
        }
        return httpx.Response(
            201,
            json={
                "token": f"installation-token-{len(requests)}",
                "expires_at": (clock.value + timedelta(hours=1)).isoformat(),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = GitHubAppTokenProvider(
            config=_config(private_key),
            http_client=client,
            clock=clock,
        )
        tokens = await asyncio.gather(*(provider() for _ in range(10)))
        assert tokens == ["installation-token-1"] * 10
        assert len(requests) == 1

        clock.value += timedelta(minutes=56)
        assert await provider() == "installation-token-2"
        assert len(requests) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"token": "", "expires_at": "2026-09-06T01:00:00+00:00"},
        {"token": "value", "expires_at": "not-a-time"},
        {"token": "value", "expires_at": "2026-09-06T00:01:00+00:00"},
    ],
)
async def test_provider_rejects_incomplete_or_expiring_response(payload: object) -> None:
    private_key, _ = _private_key()

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = GitHubAppTokenProvider(
            config=_config(private_key),
            http_client=client,
            clock=lambda: datetime(2026, 9, 6, tzinfo=UTC),
        )
        with pytest.raises(GitHubAppTokenError):
            await provider()


async def test_provider_error_never_contains_response_body() -> None:
    private_key, _ = _private_key()
    sensitive_body = "installation-token-must-not-escape"

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=sensitive_body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = GitHubAppTokenProvider(
            config=_config(private_key),
            http_client=client,
        )
        with pytest.raises(GitHubAppTokenError) as error:
            await provider()
    assert sensitive_body not in str(error.value)
