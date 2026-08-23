from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai_operator_service.adapters.resolved_models_key_vault import (
    KEY_VAULT_AUDIENCE,
    KeyVaultResolvedModelsConfig,
    KeyVaultResolvedModelsSource,
)

_NOW = datetime(2026, 8, 23, tzinfo=UTC)
_VALUE = json.dumps(
    {
        "schema_version": "1.0.0",
        "capabilities": [{"name": "t1.embedding", "status": "resolved"}],
    },
    separators=(",", ":"),
    sort_keys=True,
)


async def _token(audience: str) -> str:
    assert audience == KEY_VAULT_AUDIENCE
    return "test-token"


def _source(handler: httpx.AsyncBaseTransport) -> KeyVaultResolvedModelsSource:
    return KeyVaultResolvedModelsSource(
        config=KeyVaultResolvedModelsConfig(
            vault_url="https://example.vault.azure.net",
            secret_name="resolved-models",
        ),
        token_provider=_token,
        http_client=httpx.AsyncClient(transport=handler),
        clock=lambda: _NOW,
    )


async def test_loader_returns_digest_bound_artifact_without_exposing_secret() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/secrets/resolved-models/"
        assert request.url.params["api-version"] == "7.4"
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(
            200,
            json={
                "value": _VALUE,
                "id": "https://example.vault.azure.net/secrets/resolved-models/version1",
                "attributes": {
                    "enabled": True,
                    "exp": int((_NOW + timedelta(hours=1)).timestamp()),
                },
            },
        )

    artifact = await _source(httpx.MockTransport(handler)).load()

    assert artifact.content == _VALUE
    assert len(artifact.digest) == 64
    assert artifact.secret_version == "version1"
    assert _VALUE not in repr(artifact)
    assert "capabilities" not in str(artifact)


@pytest.mark.parametrize(
    ("vault_url", "audience"),
    [
        ("https://example.vault.azure.net", "https://vault.azure.net/.default"),
        ("https://example.vault.azure.cn", "https://vault.azure.cn/.default"),
        (
            "https://example.vault.usgovcloudapi.net",
            "https://vault.usgovcloudapi.net/.default",
        ),
    ],
)
async def test_loader_uses_the_vault_cloud_audience(vault_url: str, audience: str) -> None:
    observed: list[str] = []

    async def token_provider(value: str) -> str:
        observed.append(value)
        return "test-token"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": _VALUE})

    source = KeyVaultResolvedModelsSource(
        config=KeyVaultResolvedModelsConfig(
            vault_url=vault_url,
            secret_name="resolved-models",
        ),
        token_provider=token_provider,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        clock=lambda: _NOW,
    )

    await source.load()

    assert observed == [audience]


async def test_loader_rejects_redirect_without_following_it() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://attacker.example/secret"})

    with pytest.raises(ValueError, match="status 302"):
        await _source(httpx.MockTransport(handler)).load()

    assert len(requests) == 1


async def test_loader_bounds_token_acquisition() -> None:
    waiting = asyncio.Event()

    async def token_provider(_audience: str) -> str:
        await waiting.wait()
        return "unreachable"

    source = KeyVaultResolvedModelsSource(
        config=KeyVaultResolvedModelsConfig(
            vault_url="https://example.vault.azure.net",
            secret_name="resolved-models",
            timeout_seconds=0.01,
        ),
        token_provider=token_provider,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(500),
            )
        ),
        clock=lambda: _NOW,
    )

    with pytest.raises(ValueError, match="load timed out"):
        await source.load()


async def test_loader_bounds_the_complete_http_operation() -> None:
    waiting = asyncio.Event()

    async def handler(_request: httpx.Request) -> httpx.Response:
        await waiting.wait()
        return httpx.Response(200, json={"value": _VALUE})

    source = KeyVaultResolvedModelsSource(
        config=KeyVaultResolvedModelsConfig(
            vault_url="https://example.vault.azure.net",
            secret_name="resolved-models",
            timeout_seconds=0.01,
        ),
        token_provider=_token,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        clock=lambda: _NOW,
    )

    with pytest.raises(ValueError, match="load timed out"):
        await source.load()


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
async def test_loader_sanitizes_provider_failure(status: int) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="provider body with sensitive details")

    with pytest.raises(ValueError, match=f"status {status}") as error:
        await _source(httpx.MockTransport(handler)).load()

    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"value": "not-json"}, "artifact is invalid"),
        ({"value": "{}"}, "artifact is invalid"),
        ({"value": _VALUE, "attributes": {"enabled": False}}, "secret is disabled"),
        ({"value": _VALUE, "attributes": {"enabled": 0}}, "enabled state is invalid"),
        ({"value": _VALUE, "attributes": {"enabled": "false"}}, "enabled state is invalid"),
        (
            {"value": _VALUE, "attributes": {"exp": int(_NOW.timestamp())}},
            "secret is expired",
        ),
        ({"value": _VALUE, "attributes": {"exp": "soon"}}, "expiration is invalid"),
        ({"value": _VALUE, "attributes": {"exp": True}}, "expiration is invalid"),
    ],
)
async def test_loader_rejects_invalid_or_unusable_secret(
    payload: dict[str, object],
    message: str,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with pytest.raises(ValueError, match=message):
        await _source(httpx.MockTransport(handler)).load()


async def test_loader_rejects_oversized_artifact() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": " " * 1_048_577})

    with pytest.raises(ValueError, match="artifact exceeds"):
        await _source(httpx.MockTransport(handler)).load()


async def test_loader_rejects_excessive_artifact_nesting() -> None:
    nested = '{"next":' * 1_100 + "null" + "}" * 1_100

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": nested})

    with pytest.raises(ValueError, match="artifact is invalid"):
        await _source(httpx.MockTransport(handler)).load()


@pytest.mark.parametrize(
    "secret_id",
    [
        "https://attacker.example/secrets/resolved-models/version1",
        "https://example.vault.azure.net/secrets/other/version1",
        "https://example.vault.azure.net/secrets/resolved-models/version1/extra",
        "https://example.vault.azure.net/keys/resolved-models/version1",
    ],
)
async def test_loader_rejects_mismatched_secret_identity(secret_id: str) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": _VALUE, "id": secret_id})

    with pytest.raises(ValueError, match="secret id is invalid"):
        await _source(httpx.MockTransport(handler)).load()


async def test_loader_rejects_version_different_from_request() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": _VALUE,
                "id": "https://example.vault.azure.net/secrets/resolved-models/other",
            },
        )

    source = KeyVaultResolvedModelsSource(
        config=KeyVaultResolvedModelsConfig(
            vault_url="https://example.vault.azure.net",
            secret_name="resolved-models",
            secret_version="expected",
        ),
        token_provider=_token,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        clock=lambda: _NOW,
    )

    with pytest.raises(ValueError, match="version does not match"):
        await source.load()


@pytest.mark.parametrize(
    "changes",
    [
        {"vault_url": "http://example.vault.azure.net"},
        {"vault_url": "https://user@example.vault.azure.net"},
        {"vault_url": "https://example.vault.azure.net/path"},
        {"vault_url": "https://example.vault.azure.net:8443"},
        {"vault_url": "https://attacker.example"},
        {"secret_name": "not/valid"},
        {"secret_version": "not-valid!"},
        {"timeout_seconds": 0},
        {"timeout_seconds": 61},
    ],
)
def test_loader_rejects_invalid_configuration(changes: dict[str, object]) -> None:
    values: dict[str, object] = {
        "vault_url": "https://example.vault.azure.net",
        "secret_name": "resolved-models",
    }
    values.update(changes)

    with pytest.raises(ValueError):
        KeyVaultResolvedModelsConfig(**values)  # type: ignore[arg-type]
