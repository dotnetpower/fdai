"""Adapt fixed provider trust roots and Azure credentials for channel I/O."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from fdai_operator_service.families.conversation.channel_edge.publishers import (
    ChannelAccessToken,
)


@dataclass(frozen=True, slots=True)
class RemoteJwksConfig:
    """Configure one fixed JWKS URL and strict network and byte ceilings."""

    url: str
    timeout_seconds: float = 5.0
    max_response_bytes: int = 64_000
    max_keys: int = 32

    def __post_init__(self) -> None:
        if not self.url.startswith("https://") or len(self.url) > 2_048:
            raise ValueError("JWKS URL MUST be bounded HTTPS")
        if self.timeout_seconds <= 0 or self.max_response_bytes < 64:
            raise ValueError("JWKS network limits are invalid")
        if not 1 <= self.max_keys <= 32:
            raise ValueError("JWKS key limit is invalid")


class RemoteJwksProvider:
    """Load current RS256 keys from one startup-validated fixed HTTPS URL."""

    def __init__(self, *, config: RemoteJwksConfig, http_client: httpx.AsyncClient) -> None:
        self._config = config
        self._http = http_client

    async def warm(self) -> None:
        """Require a valid bounded key set before the edge reports readiness."""
        await self.get_keys()

    async def get_keys(self) -> Sequence[Mapping[str, Any]]:
        """Fetch a fresh bounded key set so an unknown kid can observe rotation."""
        try:
            async with self._http.stream(
                "GET",
                self._config.url,
                headers={"Accept": "application/json"},
                timeout=self._config.timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise RuntimeError("Teams JWKS provider rejected the request")
                body = await _bounded_body(
                    response.aiter_bytes(), maximum=self._config.max_response_bytes
                )
        except httpx.HTTPError as exc:
            raise RuntimeError("Teams JWKS request failed") from exc
        value = _json_object(body)
        keys = value.get("keys")
        if not isinstance(keys, list) or not 1 <= len(keys) <= self._config.max_keys:
            raise RuntimeError("Teams JWKS key count is invalid")
        if any(not isinstance(item, Mapping) for item in keys):
            raise RuntimeError("Teams JWKS keys MUST be objects")
        return tuple(item for item in keys if isinstance(item, Mapping))


class AzureChannelTokenProvider:
    """Request exactly the publisher-supplied scope from one owned credential."""

    def __init__(self, credential: AsyncTokenCredential) -> None:
        self._credential = credential

    async def get_token(self, audience: str) -> ChannelAccessToken:
        """Acquire one secret token while retaining only its requested audience proof."""
        if not audience or len(audience) > 2_048:
            raise ValueError("channel token audience MUST be bounded and non-empty")
        access_token = await self._credential.get_token(audience)
        if not isinstance(access_token.token, str) or not access_token.token:
            raise RuntimeError("channel credential returned an invalid token")
        return ChannelAccessToken(token=access_token.token, audience=audience)

    async def aclose(self) -> None:
        """Close the process-owned Azure credential exactly once at shutdown."""
        await self._credential.close()


async def _bounded_body(chunks: AsyncIterator[bytes], *, maximum: int) -> bytes:
    body = bytearray()
    async for chunk in chunks:
        body.extend(chunk)
        if len(body) > maximum:
            raise RuntimeError("Teams JWKS response exceeds the configured byte limit")
    return bytes(body)


def _json_object(body: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(
            body,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("Teams JWKS response is invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise RuntimeError("Teams JWKS response MUST be an object")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


__all__ = [
    "AzureChannelTokenProvider",
    "RemoteJwksConfig",
    "RemoteJwksProvider",
]
