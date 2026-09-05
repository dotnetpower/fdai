"""Bounded Azure Resource Manager identity read for one configured subscription."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from fdai.core.ontology_platform.subscription_scope_queries import (
    SUBSCRIPTION_SCOPE_STATES,
    SubscriptionScopeCollection,
    SubscriptionScopeObservation,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_MANAGEMENT_AUDIENCE: Final = "https://management.azure.com/.default"
_API_VERSION: Final = "2022-12-01"


@dataclass(frozen=True, slots=True)
class AzureSubscriptionScopeConfig:
    """Server-owned subscription and request ceilings for the identity read."""

    subscription_id: str
    endpoint: str = "https://management.azure.com"
    timeout_seconds: float = 8.0
    max_response_bytes: int = 65_536

    def __post_init__(self) -> None:
        try:
            canonical = str(UUID(self.subscription_id))
        except (AttributeError, ValueError) as exc:
            raise ValueError("subscription_id MUST be a canonical UUID") from exc
        if canonical != self.subscription_id.casefold():
            raise ValueError("subscription_id MUST be a canonical UUID")
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "management.azure.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("subscription endpoint MUST be the Azure management origin")
        if not 0.1 <= self.timeout_seconds <= 30:
            raise ValueError("subscription timeout_seconds MUST be in [0.1, 30]")
        if not 1_024 <= self.max_response_bytes <= 1_000_000:
            raise ValueError("subscription max_response_bytes MUST be in [1024, 1000000]")


class AzureSubscriptionScopeReader:
    """Read sanitized identity facts under exact composition-owned scope."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureSubscriptionScopeConfig,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._identity: Final = identity
        self._http: Final = http_client
        self._config: Final = config
        self._now: Final = now or (lambda: datetime.now(UTC))

    async def read(self) -> SubscriptionScopeCollection:
        """Return one verified observation or an explicit sanitized limitation."""

        observed_at = self._now()
        if observed_at.tzinfo is None:
            raise ValueError("subscription reader clock MUST be timezone-aware")
        attempt_ref = _digest(
            {
                "subscription_id": self._config.subscription_id,
                "observed_at": observed_at.isoformat(),
            }
        )
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                token = await self._identity.get_token(_MANAGEMENT_AUDIENCE)
                if (
                    not token.token
                    or token.audience != _MANAGEMENT_AUDIENCE
                    or token.expires_at.tzinfo is None
                    or token.expires_at <= observed_at
                ):
                    return self._unavailable(
                        observed_at=observed_at,
                        attempt_ref=attempt_ref,
                        limitation="identity_unavailable",
                    )
                response = await self._http.get(
                    f"{self._config.endpoint.rstrip('/')}/subscriptions/"
                    f"{self._config.subscription_id}",
                    params={"api-version": _API_VERSION},
                    headers={"Authorization": f"Bearer {token.token}"},
                    timeout=self._config.timeout_seconds,
                )
        except (TimeoutError, httpx.HTTPError, RuntimeError):
            return self._unavailable(
                observed_at=observed_at,
                attempt_ref=attempt_ref,
                limitation="source_unavailable",
            )
        if response.history or response.status_code != 200:
            return self._unavailable(
                observed_at=observed_at,
                attempt_ref=attempt_ref,
                limitation="source_unavailable",
            )
        if len(response.content) > self._config.max_response_bytes:
            return self._unavailable(
                observed_at=observed_at,
                attempt_ref=attempt_ref,
                limitation="response_too_large",
            )
        try:
            payload = response.json()
        except json.JSONDecodeError:
            return self._unavailable(
                observed_at=observed_at,
                attempt_ref=attempt_ref,
                limitation="source_response_invalid",
            )
        observation = self._observation(payload, observed_at=observed_at)
        if observation is None:
            return self._unavailable(
                observed_at=observed_at,
                attempt_ref=attempt_ref,
                limitation="source_response_invalid",
            )
        return SubscriptionScopeCollection(
            observation=observation,
            observed_at=observed_at,
            complete=True,
            limitation=None,
            attempt_ref=attempt_ref,
        )

    def _observation(
        self,
        payload: object,
        *,
        observed_at: datetime,
    ) -> SubscriptionScopeObservation | None:
        if not isinstance(payload, Mapping):
            return None
        expected_id = f"/subscriptions/{self._config.subscription_id}"
        subscription_id = payload.get("subscriptionId")
        resource_id = payload.get("id")
        display_name = payload.get("displayName")
        state = payload.get("state")
        if (
            not isinstance(subscription_id, str)
            or subscription_id.casefold() != self._config.subscription_id
            or not isinstance(resource_id, str)
            or resource_id.casefold() != expected_id
            or not isinstance(display_name, str)
            or not _bounded_label(display_name, maximum=256)
            or not isinstance(state, str)
            or state not in SUBSCRIPTION_SCOPE_STATES
        ):
            return None
        canonical_id = self._config.subscription_id
        evidence_digest = _digest(
            {
                "subscription_id": canonical_id,
                "display_name": display_name,
                "state": state,
                "observed_at": observed_at.isoformat(),
            }
        )
        return SubscriptionScopeObservation(
            display_name=display_name,
            state=state,
            masked_subscription_id=f"{canonical_id[:4]}...{canonical_id[-4:]}",
            observed_at=observed_at,
            evidence_digest=evidence_digest,
        )

    @staticmethod
    def _unavailable(
        *,
        observed_at: datetime,
        attempt_ref: str,
        limitation: str,
    ) -> SubscriptionScopeCollection:
        return SubscriptionScopeCollection(
            observation=None,
            observed_at=observed_at,
            complete=False,
            limitation=limitation,
            attempt_ref=attempt_ref,
        )


def _digest(value: Mapping[str, str]) -> str:
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def _bounded_label(value: str, *, maximum: int) -> bool:
    return bool(value.strip()) and len(value) <= maximum and all(ord(char) >= 32 for char in value)


__all__ = [
    "AzureSubscriptionScopeConfig",
    "AzureSubscriptionScopeReader",
]
