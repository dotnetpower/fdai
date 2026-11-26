"""Network and identity boundary tests for channel provider adapters."""

from __future__ import annotations

import httpx
import pytest
from fdai_operator_service.families.conversation.channel_edge.provider_adapters import (
    AzureChannelTokenProvider,
    RemoteJwksConfig,
    RemoteJwksProvider,
)


class _AccessToken:
    token = "test-access-token"


class _Credential:
    def __init__(self) -> None:
        self.scopes: list[tuple[str, ...]] = []
        self.closed = False
        self.close_count = 0

    async def get_token(self, *scopes: str, **_kwargs: object) -> _AccessToken:
        self.scopes.append(scopes)
        return _AccessToken()

    async def close(self) -> None:
        self.closed = True
        self.close_count += 1


async def test_jwks_provider_uses_fixed_url_without_redirects() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"keys": [{"kid": "key-example"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RemoteJwksProvider(
            config=RemoteJwksConfig(url="https://keys.example.com/jwks"),
            http_client=client,
        )
        keys = await provider.get_keys()

    assert str(seen[0].url) == "https://keys.example.com/jwks"
    assert keys[0]["kid"] == "key-example"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://evil.invalid"}),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, content=b'{"keys":[],"keys":[]}'),
        httpx.Response(200, json={"keys": []}),
    ],
)
async def test_jwks_provider_fails_closed_on_status_or_shape(response: httpx.Response) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: response)
    ) as client:
        provider = RemoteJwksProvider(
            config=RemoteJwksConfig(url="https://keys.example.com/jwks"),
            http_client=client,
        )
        with pytest.raises(RuntimeError):
            await provider.warm()


async def test_jwks_provider_bounds_response_body() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"x" * 65))
    ) as client:
        provider = RemoteJwksProvider(
            config=RemoteJwksConfig(
                url="https://keys.example.com/jwks",
                max_response_bytes=64,
            ),
            http_client=client,
        )
        with pytest.raises(RuntimeError, match="byte limit"):
            await provider.get_keys()


async def test_azure_token_adapter_requests_exact_scope_and_closes() -> None:
    credential = _Credential()
    provider = AzureChannelTokenProvider(credential)  # type: ignore[arg-type]

    token = await provider.get_token("https://api.botframework.com/.default")
    await provider.aclose()
    await provider.aclose()

    assert credential.scopes == [("https://api.botframework.com/.default",)]
    assert credential.closed is True
    assert credential.close_count == 1
    assert "test-access-token" not in repr(token)
