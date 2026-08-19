"""Verify Bot Framework service tokens with bounded injected JWKS data."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

import jwt

_MAX_JWKS_KEYS = 32


class TeamsJwksProvider(Protocol):
    """Return the current bounded Bot Framework JSON Web Key Set."""

    async def get_keys(self) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class TeamsTokenConfig:
    """Configure exact Bot application and service-token validation policy."""

    application_id: str
    issuer: str = "https://api.botframework.com"
    algorithms: tuple[str, ...] = ("RS256",)
    leeway: timedelta = timedelta(seconds=60)

    def __post_init__(self) -> None:
        if not self.application_id or len(self.application_id) > 200:
            raise ValueError("Teams application_id MUST be bounded and non-empty")
        if self.issuer != "https://api.botframework.com":
            raise ValueError("Teams issuer MUST be the Bot Framework service issuer")
        if self.algorithms != ("RS256",):
            raise ValueError("Teams token algorithms MUST contain only RS256")
        if not timedelta(0) <= self.leeway <= timedelta(minutes=5):
            raise ValueError("Teams token leeway is outside the bounded range")


@dataclass(frozen=True, slots=True)
class VerifiedTeamsServiceToken:
    """Retain claims after signature, time, audience, and issuer verification."""

    service_url: str
    key_id: str


class TeamsAuthenticationError(ValueError):
    """A Teams service token failed closed without exposing token content."""


class TeamsServiceTokenVerifier:
    """Resolve one RS256 key by kid and verify every decision-critical claim."""

    def __init__(self, *, config: TeamsTokenConfig, jwks: TeamsJwksProvider) -> None:
        self._config = config
        self._jwks = jwks
        self._keys: dict[str, jwt.PyJWK] = {}
        self._lock = asyncio.Lock()

    async def verify(self, authorization: str) -> VerifiedTeamsServiceToken:
        """Verify one bearer token with a fixed algorithm and bounded key source."""
        token = _bearer_token(authorization)
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise TeamsAuthenticationError("Teams service token header is invalid") from exc
        key_id = header.get("kid")
        algorithm = header.get("alg")
        if not isinstance(key_id, str) or not key_id or len(key_id) > 256:
            raise TeamsAuthenticationError("Teams service token key id is invalid")
        if algorithm != "RS256":
            raise TeamsAuthenticationError("Teams service token algorithm is not allowed")
        key = await self._resolve_key(key_id)
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=list(self._config.algorithms),
                audience=self._config.application_id,
                issuer=self._config.issuer,
                leeway=self._config.leeway,
                options={"require": ["aud", "iss", "exp", "nbf", "serviceurl"]},
            )
        except jwt.PyJWTError as exc:
            raise TeamsAuthenticationError("Teams service token verification failed") from exc
        service_url = claims.get("serviceurl")
        if not isinstance(service_url, str) or not service_url:
            raise TeamsAuthenticationError("Teams service token service URL is invalid")
        return VerifiedTeamsServiceToken(service_url=service_url, key_id=key_id)

    async def _resolve_key(self, key_id: str) -> jwt.PyJWK:
        key = self._keys.get(key_id)
        if key is not None:
            return key
        async with self._lock:
            key = self._keys.get(key_id)
            if key is not None:
                return key
            keys = await self._jwks.get_keys()
            if not 1 <= len(keys) <= _MAX_JWKS_KEYS:
                raise TeamsAuthenticationError("Teams JWKS key count is invalid")
            refreshed: dict[str, jwt.PyJWK] = {}
            try:
                for value in keys:
                    candidate = jwt.PyJWK.from_dict(dict(value), algorithm="RS256")
                    candidate_id = candidate.key_id
                    if (
                        not isinstance(candidate_id, str)
                        or not candidate_id
                        or candidate_id in refreshed
                    ):
                        raise TeamsAuthenticationError("Teams JWKS key ids are invalid")
                    refreshed[candidate_id] = candidate
            except jwt.PyJWTError as exc:
                raise TeamsAuthenticationError("Teams JWKS contains an invalid key") from exc
            self._keys = refreshed
            key = refreshed.get(key_id)
            if key is None:
                raise TeamsAuthenticationError("Teams service token key id is unknown")
            return key


def _bearer_token(value: str) -> str:
    scheme, separator, token = value.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token or " " in token:
        raise TeamsAuthenticationError("Teams authorization header is invalid")
    return token


__all__ = [
    "TeamsAuthenticationError",
    "TeamsJwksProvider",
    "TeamsServiceTokenVerifier",
    "TeamsTokenConfig",
    "VerifiedTeamsServiceToken",
]
