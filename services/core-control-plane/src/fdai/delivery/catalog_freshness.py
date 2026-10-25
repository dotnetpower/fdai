"""Installation-side freshness of the Release Hub's signed catalog metadata.

The installation verifies the public root chain, snapshot and timestamp itself against a pinned
root, so no Agent, Hub or event carries authority for the result. An expired or unverifiable
timestamp returns operator-override promotions to shadow mode, which only lowers authority.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from fdai_service_contracts.catalog_integrity import (
    CatalogRootRecord,
    CatalogSnapshotRecord,
    CatalogTimestampRecord,
    evaluate_catalog_integrity,
)
from fdai_service_contracts.catalog_metadata import (
    MAX_METADATA_BYTES,
    parse_metadata,
    role_verifier,
)
from fdai_service_contracts.catalog_roles import CatalogRootChainError, verify_root_chain

_LOGGER = logging.getLogger("fdai.catalog_freshness")
_PREFIX = "FDAI_CATALOG_FRESHNESS_"
_MIN_REFRESH_SECONDS = 30.0
_RETRY_SECONDS = 60.0
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})

Fetch = Callable[[str], Awaitable[bytes]]
Clock = Callable[[], datetime]


class PromotionFreshnessTarget(Protocol):
    def set_catalog_timestamp_expired(self, expired: bool) -> None: ...


@dataclass(frozen=True, slots=True)
class CatalogFreshnessConfig:
    metadata_url: str
    root_key_ids: frozenset[str]
    root_threshold: int
    refresh_seconds: float = 300.0
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        parts = urlsplit(self.metadata_url)
        loopback = parts.hostname in _LOOPBACK
        if parts.scheme not in {"https", "http"} or not parts.hostname:
            raise ValueError("catalog freshness metadata URL must be an absolute http(s) URL")
        if parts.scheme == "http" and not loopback:
            raise ValueError("catalog freshness metadata URL must use https")
        if parts.username or parts.password or parts.fragment:
            raise ValueError("catalog freshness metadata URL must not carry credentials")
        if not self.root_key_ids or not 1 <= self.root_threshold <= len(self.root_key_ids):
            raise ValueError("catalog freshness root pin needs key ids and a valid threshold")
        if self.refresh_seconds < _MIN_REFRESH_SECONDS or self.timeout_seconds <= 0:
            raise ValueError("catalog freshness refresh must be at least 30 seconds")

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> CatalogFreshnessConfig | None:
        """Return None when the feature is not selected; a partial selection is an error."""

        url = environment.get(_PREFIX + "METADATA_URL", "").strip()
        if not url:
            return None
        key_ids = frozenset(
            item.strip()
            for item in environment.get(_PREFIX + "ROOT_KEY_IDS", "").split(",")
            if item.strip()
        )
        threshold = environment.get(_PREFIX + "ROOT_THRESHOLD", "").strip()
        refresh = environment.get(_PREFIX + "REFRESH_SECONDS", "").strip()
        return cls(
            metadata_url=url,
            root_key_ids=key_ids,
            root_threshold=int(threshold) if threshold else len(key_ids),
            refresh_seconds=float(refresh) if refresh else 300.0,
        )


@dataclass(frozen=True, slots=True)
class _Verified:
    root: CatalogRootRecord
    snapshot: CatalogSnapshotRecord
    timestamp: CatalogTimestampRecord

    @property
    def valid_until(self) -> datetime:
        return min(self.timestamp.expires_at, self.snapshot.expires_at, self.root.expires_at)


class CatalogFreshnessMonitor:
    """Keep the promotion registry's catalog-expiry flag equal to the verified metadata state."""

    def __init__(
        self,
        config: CatalogFreshnessConfig,
        *,
        fetch: Fetch | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._config = config
        self._fetch = fetch or _HttpFetch(config.timeout_seconds)
        self._clock = clock
        self._lock = asyncio.Lock()
        self._verified: _Verified | None = None
        self._next_poll: datetime | None = None
        self._last_failure: str | None = None
        self._expired: bool | None = None

    async def apply(self, registry: PromotionFreshnessTarget) -> bool:
        """Refresh when due, then set the flag. This never raises: unknown state is expired."""

        async with self._lock:
            now = self._clock()
            if self._next_poll is None or now >= self._next_poll:
                await self._poll(now)
            expired = self._is_expired(now)
            registry.set_catalog_timestamp_expired(expired)
            if expired != self._expired:
                _LOGGER.warning(
                    "catalog_freshness_changed",
                    extra={"expired": expired, "reason": self._reason(expired)},
                )
            self._expired = expired
            return expired

    def status(self) -> dict[str, object]:
        verified = self._verified
        return {
            "expired": self._expired,
            "reason": self._reason(bool(self._expired)),
            "timestamp_version": verified.timestamp.version if verified else None,
            "valid_until": verified.valid_until.isoformat() if verified else None,
        }

    def _is_expired(self, now: datetime) -> bool:
        return self._verified is None or now >= self._verified.valid_until

    def _reason(self, expired: bool) -> str:
        if not expired:
            return "fresh"
        return self._last_failure or "catalog_timestamp_expired"

    async def _poll(self, now: datetime) -> None:
        try:
            raw = await asyncio.wait_for(
                self._fetch(self._config.metadata_url), self._config.timeout_seconds + 1
            )
            self._accept(raw, now)
            self._last_failure = None
            self._next_poll = _after(now, self._config.refresh_seconds)
        except CatalogRootChainError as error:
            self._reject(now, error.reason_code)
        except (TimeoutError, httpx.HTTPError, OSError):
            self._reject(now, "catalog_metadata_unavailable")
        except ValueError as error:
            self._reject(now, str(error) or "catalog_metadata_malformed")

    def _reject(self, now: datetime, reason: str) -> None:
        # Keep the last verified state: a failure never extends freshness, and the local clock
        # still ends it at the signed expiry.
        self._last_failure = reason
        self._next_poll = _after(now, min(_RETRY_SECONDS, self._config.refresh_seconds))

    def _accept(self, raw: bytes, now: datetime) -> None:
        bundle = parse_metadata(raw)
        root = verify_root_chain(
            bundle.root_chain,
            pinned_root_key_ids=self._config.root_key_ids,
            pinned_threshold=self._config.root_threshold,
            make_verifier=role_verifier,
        )
        floor = self._verified
        decision = evaluate_catalog_integrity(
            root=root,
            snapshot=bundle.snapshot,
            timestamp=bundle.timestamp,
            verify_signature=role_verifier(root.public_keys),
            trusted_now=now,
            minimum_root_version=floor.root.version if floor else 1,
            minimum_snapshot_version=floor.snapshot.version if floor else 1,
            minimum_timestamp_version=floor.timestamp.version if floor else 1,
            previous_max_recall_sequence=(
                max(floor.snapshot.recall_sequences, default=0) if floor else 0
            ),
        )
        if not decision.allowed:
            raise ValueError(decision.reason_code)
        self._verified = _Verified(root, bundle.snapshot, bundle.timestamp)


def _after(now: datetime, seconds: float) -> datetime:
    return datetime.fromtimestamp(now.timestamp() + seconds, UTC)


class _HttpFetch:
    """Bounded, redirect-free GET of public metadata."""

    def __init__(self, timeout_seconds: float) -> None:
        self._timeout = timeout_seconds

    async def __call__(self, url: str) -> bytes:
        async with (
            httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client,
            client.stream("GET", url, headers={"Accept": "application/json"}) as response,
        ):
            if response.status_code != 200:
                raise httpx.HTTPError("catalog metadata response was not 200")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_METADATA_BYTES:
                    raise ValueError("catalog_metadata_too_large")
            return bytes(body)


def build_catalog_freshness_monitor(
    environment: Mapping[str, str],
) -> CatalogFreshnessMonitor | None:
    config = CatalogFreshnessConfig.from_environment(environment)
    return None if config is None else CatalogFreshnessMonitor(config)


__all__ = [
    "CatalogFreshnessConfig",
    "CatalogFreshnessMonitor",
    "build_catalog_freshness_monitor",
]
