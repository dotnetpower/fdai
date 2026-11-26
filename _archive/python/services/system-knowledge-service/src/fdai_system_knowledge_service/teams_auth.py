"""Bot Framework service-token verification for the knowledge bot."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

import httpx
import jwt

_MAX_JWKS_KEYS = 32


class TeamsIngressError(ValueError):
    """An activity failed before knowledge retrieval."""

    def __init__(self, message: str, *, code: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class VerifiedServiceToken:
    """Bot service identity after signature and claim verification."""

    service_url: str
    key_id: str


class ServiceTokenVerifier(Protocol):
    """Verify one Bot service authorization header."""

    async def verify(self, authorization: str) -> VerifiedServiceToken: ...

    async def warm(self) -> None: ...


class JwksProvider(Protocol):
    """Return a bounded Bot service JSON Web Key Set."""

    async def get_keys(self) -> Sequence[Mapping[str, Any]]: ...


class RemoteJwksProvider:
    """Fetch a bounded JWKS document from one configured HTTPS endpoint."""

    def __init__(
        self,
        *,
        url: str,
        http_client: httpx.AsyncClient,
        timeout_seconds: float = 5.0,
        max_bytes: int = 128_000,
    ) -> None:
        self._url = url
        self._http = http_client
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes

    async def get_keys(self) -> Sequence[Mapping[str, Any]]:
        async with self._http.stream(
            "GET",
            self._url,
            timeout=self._timeout,
            follow_redirects=False,
            headers={"Accept": "application/json"},
        ) as response:
            response.raise_for_status()
            body = await _bounded_bytes(response.aiter_bytes(), maximum=self._max_bytes)
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Teams JWKS response is invalid JSON") from exc
        keys = payload.get("keys") if isinstance(payload, Mapping) else None
        if (
            not isinstance(keys, list)
            or not 1 <= len(keys) <= _MAX_JWKS_KEYS
            or any(not isinstance(item, Mapping) for item in keys)
        ):
            raise RuntimeError("Teams JWKS response contains invalid keys")
        return tuple(keys)


class PyJwtServiceTokenVerifier:
    """Verify fixed-algorithm Bot Framework service tokens with bounded JWKS caching."""

    def __init__(
        self,
        *,
        application_id: str,
        jwks: JwksProvider,
        cache_ttl: timedelta = timedelta(minutes=5),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._application_id = application_id
        self._jwks = jwks
        self._cache_ttl = cache_ttl
        self._clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._refreshed_at: float | None = None
        self._lock = asyncio.Lock()

    async def warm(self) -> None:
        """Load and validate the current key set before readiness opens."""

        await self._refresh()

    async def verify(self, authorization: str) -> VerifiedServiceToken:
        token = _bearer_token(authorization)
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise _authentication_error("Teams service token header is invalid") from exc
        key_id = header.get("kid")
        if (
            header.get("alg") != "RS256"
            or not isinstance(key_id, str)
            or not key_id
            or len(key_id) > 256
        ):
            raise _authentication_error("Teams service token algorithm or key id is invalid")
        key = await self._key(key_id)
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self._application_id,
                issuer="https://api.botframework.com",
                leeway=timedelta(seconds=60),
                options={"require": ["aud", "iss", "exp", "nbf", "serviceurl"]},
            )
        except jwt.PyJWTError as exc:
            raise _authentication_error("Teams service token verification failed") from exc
        service_url = claims.get("serviceurl")
        if not isinstance(service_url, str) or not service_url:
            raise _authentication_error("Teams service token service URL is invalid")
        return VerifiedServiceToken(service_url=service_url, key_id=key_id)

    async def _key(self, key_id: str) -> jwt.PyJWK:
        now = self._clock()
        if (
            key_id in self._keys
            and self._refreshed_at is not None
            and 0 <= now - self._refreshed_at < self._cache_ttl.total_seconds()
        ):
            return self._keys[key_id]
        async with self._lock:
            await self._refresh()
            try:
                return self._keys[key_id]
            except KeyError as exc:
                raise _authentication_error("Teams service token key id is unknown") from exc

    async def _refresh(self) -> None:
        raw_keys = await self._jwks.get_keys()
        refreshed: dict[str, jwt.PyJWK] = {}
        for value in raw_keys:
            try:
                key = jwt.PyJWK.from_dict(dict(value), algorithm="RS256")
            except jwt.PyJWTError as exc:
                raise RuntimeError("Teams JWKS contains an invalid key") from exc
            if not key.key_id or key.key_id in refreshed:
                raise RuntimeError("Teams JWKS key ids are invalid")
            refreshed[key.key_id] = key
        self._keys = refreshed
        self._refreshed_at = self._clock()


def _authentication_error(message: str) -> TeamsIngressError:
    return TeamsIngressError(
        message,
        code="invalid_service_identity",
        http_status=401,
    )


def _bearer_token(value: str) -> str:
    scheme, separator, token = value.partition(" ")
    if separator != " " or scheme.casefold() != "bearer" or not token or " " in token:
        raise _authentication_error("Teams authorization header is invalid")
    return token


async def _bounded_bytes(chunks: AsyncIterator[bytes], *, maximum: int) -> bytes:
    body = bytearray()
    async for chunk in chunks:
        body.extend(chunk)
        if len(body) > maximum:
            raise RuntimeError("Teams JWKS response exceeds the configured bound")
    return bytes(body)


__all__ = [
    "JwksProvider",
    "PyJwtServiceTokenVerifier",
    "RemoteJwksProvider",
    "ServiceTokenVerifier",
    "TeamsIngressError",
    "VerifiedServiceToken",
]
