"""Bounded Teams connector publishing for system-knowledge replies."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx

BOT_SCOPE = "https://api.botframework.com/.default"


class TeamsPublishError(RuntimeError):
    """A provider send failed with a known acknowledgement posture."""

    def __init__(self, message: str, *, code: str, ambiguous: bool) -> None:
        super().__init__(message)
        self.code = code
        self.ambiguous = ambiguous


@dataclass(frozen=True, slots=True)
class ChannelAccessToken:
    """One outbound token and its requested audience."""

    token: str
    audience: str


class ChannelTokenProvider(Protocol):
    """Acquire a short-lived Bot connector token."""

    async def get_token(self, audience: str) -> ChannelAccessToken: ...

    async def aclose(self) -> None: ...


class AzureChannelTokenProvider:
    """Adapt one Azure credential without exposing its token."""

    def __init__(self, credential: Any) -> None:
        self._credential = credential

    async def get_token(self, audience: str) -> ChannelAccessToken:
        token = await self._credential.get_token(audience)
        if not token.token:
            raise RuntimeError("Teams credential returned an empty token")
        return ChannelAccessToken(token=token.token, audience=audience)

    async def aclose(self) -> None:
        await self._credential.close()


class TeamsPublisher:
    """Send one bounded reply through the authenticated conversation endpoint."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        tokens: ChannelTokenProvider,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._http = http_client
        self._tokens = tokens
        self._timeout = timeout_seconds

    async def send(
        self,
        *,
        conversation_id: str,
        service_url: str,
        payload: Mapping[str, object],
    ) -> str:
        """Return the provider activity id or a classified send failure."""

        token = await self._tokens.get_token(BOT_SCOPE)
        if token.audience != BOT_SCOPE:
            raise TeamsPublishError(
                "Teams token audience is invalid",
                code="identity_audience_mismatch",
                ambiguous=False,
            )
        url = f"{service_url}/v3/conversations/{quote(conversation_id, safe='')}/activities"
        try:
            async with self._http.stream(
                "POST",
                url,
                json=dict(payload),
                headers={"Authorization": f"Bearer {token.token}", "Accept": "application/json"},
                timeout=self._timeout,
                follow_redirects=False,
            ) as response:
                if response.status_code not in {200, 201, 202}:
                    raise TeamsPublishError(
                        "Teams provider rejected the reply",
                        code="provider_rejected",
                        ambiguous=False,
                    )
                body = await _bounded_body(response.aiter_bytes(), maximum=8192)
        except TeamsPublishError:
            raise
        except httpx.HTTPError as exc:
            raise TeamsPublishError(
                "Teams reply acknowledgement was interrupted",
                code="transport_error",
                ambiguous=True,
            ) from exc
        acknowledgement = _json_object(body)
        activity_id = acknowledgement.get("id")
        if not isinstance(activity_id, str) or not activity_id or len(activity_id) > 256:
            raise TeamsPublishError(
                "Teams reply acknowledgement is invalid",
                code="invalid_acknowledgement",
                ambiguous=True,
            )
        return activity_id

    async def aclose(self) -> None:
        """Close the service-owned token provider."""

        await self._tokens.aclose()


def _json_object(body: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(body, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise TeamsPublishError(
            "Teams reply acknowledgement is invalid JSON",
            code="invalid_acknowledgement",
            ambiguous=True,
        ) from exc
    if not isinstance(value, Mapping):
        raise TeamsPublishError(
            "Teams reply acknowledgement MUST be an object",
            code="invalid_acknowledgement",
            ambiguous=True,
        )
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


async def _bounded_body(chunks: AsyncIterator[bytes], *, maximum: int) -> bytes:
    body = bytearray()
    async for chunk in chunks:
        body.extend(chunk)
        if len(body) > maximum:
            raise TeamsPublishError(
                "Teams provider response exceeds the configured bound",
                code="acknowledgement_too_large",
                ambiguous=True,
            )
    return bytes(body)


__all__ = [
    "AzureChannelTokenProvider",
    "ChannelAccessToken",
    "ChannelTokenProvider",
    "TeamsPublishError",
    "TeamsPublisher",
]
