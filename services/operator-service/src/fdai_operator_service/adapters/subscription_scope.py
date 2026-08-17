"""Catalog-backed intent recognition and bounded Azure subscription identity reads."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unicodedata import normalize
from uuid import UUID

import httpx
import yaml
from fdai_service_contracts import query_content_digest

ARM_AUDIENCE = "https://management.azure.com/.default"
ARM_ENDPOINT = "https://management.azure.com"
ARM_RESOURCE = "https://management.azure.com/"
_API_VERSION = "2022-12-01"
_MAX_RESPONSE_BYTES = 65_536
_MAX_TEXT_CHARS = 256
_WORD_SEPARATOR = re.compile(r"[^\w]+", flags=re.UNICODE)

TokenProvider = Callable[[str], Awaitable[str]]
Clock = Callable[[], datetime]


class SubscriptionScopeCatalogError(ValueError):
    """Report an invalid catalog without retaining catalog payloads."""


class SubscriptionScopeProviderError(RuntimeError):
    """Report bounded provider unavailability without exposing provider details."""


@dataclass(frozen=True, slots=True)
class SubscriptionScopeIntentCatalog:
    """Match one read-only subscription identity intent from catalog-owned terms."""

    identity_terms: tuple[str, ...]
    excluded_terms: tuple[str, ...]
    suffixes: tuple[str, ...]

    def matches(self, utterance: str) -> bool:
        """Return true only for a complete read intent without health or mutation terms."""
        normalized = _normalized_text(utterance, suffixes=self.suffixes)
        if not normalized:
            return False
        return _contains_term(normalized, self.identity_terms) and not _contains_term(
            normalized, self.excluded_terms
        )


@dataclass(frozen=True, slots=True)
class SubscriptionScopeEvidence:
    """Expose only bounded display fields and content-addressed read evidence."""

    display_name: str
    state: str
    masked_subscription_id: str
    observed_at: datetime
    evidence_ref: str
    receipt_digest: str
    execution_authority: bool = False


def load_subscription_scope_intent_catalog(path: Path) -> SubscriptionScopeIntentCatalog:
    """Load the subscription identity subset of the inventory language catalog."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise TypeError
        signals = _mapping(payload.get("signals"))
        query_kinds = _mapping(payload.get("query_kinds"))
        suffix_values = payload.get("suffixes")
        if not isinstance(suffix_values, list | tuple) or not suffix_values:
            raise TypeError
        suffixes = tuple(
            sorted(
                (value for value in suffix_values if isinstance(value, str) and value),
                key=len,
                reverse=True,
            )
        )
        if len(suffixes) != len(suffix_values):
            raise ValueError
        identity_terms = _terms(
            query_kinds,
            "subscription_scope_identity",
            suffixes=suffixes,
        )
        excluded_terms = tuple(
            term
            for key in ("mutation", "state_inspection", "platform_health", "diagnosis")
            for term in _terms(signals, key, suffixes=suffixes)
        )
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise SubscriptionScopeCatalogError("subscription scope intent catalog is invalid") from exc
    return SubscriptionScopeIntentCatalog(
        identity_terms=identity_terms,
        excluded_terms=excluded_terms,
        suffixes=suffixes,
    )


class AzureSubscriptionScopeProvider:
    """Read one server-configured subscription through ARM with no scope input."""

    def __init__(
        self,
        *,
        subscription_id: str,
        token_provider: TokenProvider,
        http_client: httpx.AsyncClient,
        now: Clock | None = None,
        timeout_seconds: float = 10.0,
        cache_seconds: float = 30.0,
    ) -> None:
        try:
            canonical_subscription_id = str(UUID(subscription_id))
        except ValueError as exc:
            raise ValueError(
                "subscription scope provider requires a canonical subscription id"
            ) from exc
        if not 0 < timeout_seconds <= 30:
            raise ValueError("subscription scope timeout MUST be in (0, 30]")
        if not 0 <= cache_seconds <= 300:
            raise ValueError("subscription scope cache_seconds MUST be in [0, 300]")
        self._subscription_id = canonical_subscription_id
        self._token_provider = token_provider
        self._http = http_client
        self._now = now or (lambda: datetime.now(UTC))
        self._timeout_seconds = timeout_seconds
        self._cache_seconds = cache_seconds
        self._cached: SubscriptionScopeEvidence | None = None
        self._read_lock = asyncio.Lock()

    async def read(self) -> SubscriptionScopeEvidence:
        """Return verified subscription metadata or one detail-free provider error."""
        async with self._read_lock:
            now = self._aware_now()
            cached = self._cached
            if cached is not None and now - cached.observed_at <= timedelta(
                seconds=self._cache_seconds
            ):
                return cached
            result = await self._read_uncached(observed_at=now)
            self._cached = result
            return result

    async def _read_uncached(self, *, observed_at: datetime) -> SubscriptionScopeEvidence:
        try:
            token = await self._token_provider(ARM_AUDIENCE)
        except Exception as exc:  # noqa: BLE001 - identity details stay behind typed unavailability
            raise SubscriptionScopeProviderError(
                "subscription scope evidence is unavailable"
            ) from exc
        try:
            if not token:
                raise ValueError("empty token")
            response = await self._http.get(
                f"{ARM_ENDPOINT}/subscriptions/{self._subscription_id}",
                params={"api-version": _API_VERSION},
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            if len(response.content) > _MAX_RESPONSE_BYTES:
                raise ValueError("oversized response")
            payload = response.json()
            if not isinstance(payload, Mapping):
                raise TypeError("invalid response")
            returned_id = _bounded_text(payload.get("subscriptionId"), "subscription id")
            if returned_id.casefold() != self._subscription_id.casefold():
                raise ValueError("scope mismatch")
            display_name = _bounded_text(payload.get("displayName"), "display name")
            state = _bounded_text(payload.get("state"), "state")
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise SubscriptionScopeProviderError(
                "subscription scope evidence is unavailable"
            ) from exc

        scope_digest = query_content_digest({"subscription_id": self._subscription_id})
        receipt_digest = query_content_digest(
            {
                "authority": "azure.resource_manager.subscription",
                "scope_digest": scope_digest,
                "display_name": display_name,
                "state": state,
                "observed_at": observed_at.isoformat(),
                "execution_authority": False,
            }
        )
        return SubscriptionScopeEvidence(
            display_name=display_name,
            state=state,
            masked_subscription_id=_mask_subscription_id(self._subscription_id),
            observed_at=observed_at,
            evidence_ref=f"azure-subscription:{receipt_digest.removeprefix('sha256:')}",
            receipt_digest=receipt_digest,
        )

    def _aware_now(self) -> datetime:
        observed_at = self._now()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise SubscriptionScopeProviderError("subscription scope evidence is unavailable")
        return observed_at.astimezone(UTC)


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError
    return value


def _terms(
    container: Mapping[str, Any],
    key: str,
    *,
    suffixes: tuple[str, ...],
) -> tuple[str, ...]:
    entry = _mapping(container.get(key))
    values = entry.get("terms")
    if not isinstance(values, list | tuple) or not values:
        raise TypeError
    terms = tuple(
        _normalized_text(value, suffixes=suffixes) for value in values if isinstance(value, str)
    )
    if len(terms) != len(values) or any(not term for term in terms):
        raise ValueError
    return terms


def _normalized_text(value: str, *, suffixes: tuple[str, ...]) -> str:
    normalized = normalize("NFC", value).casefold().strip()
    parts = tuple(part for part in _WORD_SEPARATOR.split(normalized) if part)
    return " ".join(_strip_suffix(part, suffixes) for part in parts)


def _strip_suffix(token: str, suffixes: tuple[str, ...]) -> str:
    for suffix in suffixes:
        if token.endswith(suffix) and len(token) >= len(suffix) + 2:
            return token[: -len(suffix)]
    return token


def _contains_term(utterance: str, terms: tuple[str, ...]) -> bool:
    padded = f" {utterance} "
    return any(f" {term} " in padded for term in terms)


def _bounded_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT_CHARS:
        raise ValueError(f"subscription scope {label} is invalid")
    return value.strip()


def _mask_subscription_id(subscription_id: str) -> str:
    return f"{subscription_id[:4]}...{subscription_id[-4:]}"


__all__ = [
    "ARM_AUDIENCE",
    "ARM_RESOURCE",
    "AzureSubscriptionScopeProvider",
    "SubscriptionScopeCatalogError",
    "SubscriptionScopeEvidence",
    "SubscriptionScopeIntentCatalog",
    "SubscriptionScopeProviderError",
    "load_subscription_scope_intent_catalog",
]
