"""Durable, read-only environment-profile refresh over the existing StateStore."""

from __future__ import annotations

import asyncio
import hashlib
import math
import secrets
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.core.deploy_preflight.environment_profile import (
    DeploymentEnvironmentProfile,
    build_profile,
)
from fdai.shared.providers.state_store import StateStore

ProfileBuilder = Callable[[str, datetime], Awaitable[DeploymentEnvironmentProfile]]
_KEY_PREFIX = "deploy-preflight:environment-profile:"
_MAX_CONFLICT_RETRIES = 8


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("environment profile clock MUST be timezone-aware")
    return value.astimezone(UTC)


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("environment profile timestamp MUST be text")
    return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _profile(
    record: Mapping[str, Any], scope: str, now: datetime, max_age: int
) -> DeploymentEnvironmentProfile | None:
    raw = record.get("profile")
    if raw is None:
        return None
    if not isinstance(raw, dict) or raw.get("scope") != scope:
        raise ValueError("persisted environment profile has an invalid scope or shape")
    rules = raw.get("rule_ids")
    counts = raw.get("resource_type_counts")
    metadata = raw.get("metadata")
    if (
        not isinstance(rules, list)
        or not all(isinstance(rule, str) for rule in rules)
        or not isinstance(counts, dict)
        or not all(isinstance(k, str) and type(v) is int for k, v in counts.items())
        or not isinstance(metadata, dict)
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in metadata.items())
    ):
        raise ValueError("persisted environment profile has invalid fields")
    age = (now - _timestamp(raw.get("captured_at"))).total_seconds()
    if age < 0 or age > max_age:
        return None
    return build_profile(
        scope=scope,
        rule_ids=rules,
        resource_type_counts=counts,
        captured_at=raw["captured_at"],
        metadata=metadata,
    )


class EnvironmentProfileRefreshTask:
    """Single-scope CAS refresh with a restartable lease and delta invalidation.

    Builders perform bounded read-only probes. This state is a cache, never an
    authorization or deployment-readiness receipt. Readers recheck the durable
    record, so a different process cannot serve a locally cached stale profile.
    """

    def __init__(
        self,
        *,
        state_store: StateStore,
        builder: ProfileBuilder | None = None,
        clock: Callable[[], datetime] | None = None,
        max_age_seconds: int = 300,
        lease_seconds: int = 60,
        deadline_seconds: float = 30.0,
    ) -> None:
        if max_age_seconds < 1 or lease_seconds < 1:
            raise ValueError("environment profile age and lease MUST be positive")
        if not math.isfinite(deadline_seconds) or deadline_seconds <= 0:
            raise ValueError("environment profile deadline MUST be finite and positive")
        self._store = state_store
        self._builder = builder
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_age = max_age_seconds
        self._lease_seconds = lease_seconds
        self._deadline = deadline_seconds

    @staticmethod
    def _key(scope: str) -> str:
        if not scope.strip():
            raise ValueError("environment profile scope MUST be non-empty")
        return _KEY_PREFIX + hashlib.sha256(scope.encode("utf-8")).hexdigest()

    async def _read(self, key: str) -> dict[str, Any] | None:
        raw = await self._store.read_state(key)
        if raw is None:
            return None
        revision = raw.get("revision")
        if (
            type(revision) is not int
            or revision < 1
            or not isinstance(raw.get("invalidation_token"), str)
            or (raw.get("profile") is not None and not isinstance(raw.get("profile"), dict))
            or (raw.get("lease") is not None and not isinstance(raw.get("lease"), dict))
        ):
            raise ValueError("persisted environment profile state is malformed")
        return dict(raw)

    async def _create(self, key: str) -> None:
        await self._store.write_state_if_absent(
            key,
            {"revision": 1, "invalidation_token": "", "profile": None, "lease": None},
        )

    async def get_fresh(self, scope: str) -> DeploymentEnvironmentProfile | None:
        """Read the durable cache, rejecting an expired or future-dated profile."""
        record = await self._read(self._key(scope))
        if record is None:
            return None
        return _profile(record, scope, _utc(self._clock()), self._max_age)

    async def invalidate(self, scope: str, delta_token: str) -> bool:
        """Invalidate after a complete Inventory delta, before its cursor commits.

        Identical stream redelivery is a no-op. A failed write propagates so
        the Inventory cursor cannot advance without invalidating this profile.
        """
        if not isinstance(delta_token, str) or not delta_token:
            raise ValueError("inventory delta token MUST be non-empty")
        key = self._key(scope)
        token = hashlib.sha256(delta_token.encode("utf-8")).hexdigest()
        for _ in range(_MAX_CONFLICT_RETRIES):
            current = await self._read(key)
            if current is None:
                if await self._store.write_state_if_absent(
                    key,
                    {"revision": 1, "invalidation_token": token, "profile": None, "lease": None},
                ):
                    return True
                continue
            if current["invalidation_token"] == token:
                return False
            replacement = {
                **current,
                "revision": current["revision"] + 1,
                "invalidation_token": token,
                "profile": None,
                "lease": None,
            }
            if await self._store.compare_and_set_state(
                key, replacement, expected_revision=current["revision"]
            ):
                return True
        raise RuntimeError("environment profile invalidation conflicted repeatedly")

    async def run_once(self, scope: str) -> DeploymentEnvironmentProfile | None:
        """Claim one due refresh; expired leases can be reclaimed after restart."""
        if self._builder is None:
            raise RuntimeError("environment profile refresh requires a read-only builder")
        key = self._key(scope)
        for _ in range(_MAX_CONFLICT_RETRIES):
            current = await self._read(key)
            if current is None:
                await self._create(key)
                continue
            now = _utc(self._clock())
            fresh = _profile(current, scope, now, self._max_age)
            if fresh is not None:
                return fresh
            lease = current["lease"]
            if lease is not None:
                try:
                    if _timestamp(lease["until"]) > now:
                        return None
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError("persisted environment profile lease is malformed") from exc
            token = secrets.token_hex(16)
            until = now + timedelta(seconds=self._lease_seconds)
            claimed = {
                **current,
                "revision": current["revision"] + 1,
                "lease": {"token": token, "until": until.isoformat()},
            }
            if await self._store.compare_and_set_state(
                key, claimed, expected_revision=current["revision"]
            ):
                break
        else:
            raise RuntimeError("environment profile refresh conflicted repeatedly")

        try:
            async with asyncio.timeout(self._deadline):
                built = await self._builder(scope, now)
            if not isinstance(built, DeploymentEnvironmentProfile):
                raise ValueError("environment profile builder returned an invalid profile")
            observed = _utc(self._clock())
            age = (observed - _timestamp(built.captured_at)).total_seconds()
            if built.scope != scope or age < 0 or age > self._max_age:
                raise ValueError("environment profile builder returned stale or mismatched data")
            if observed >= until:
                return None
            published = {
                **claimed,
                "revision": claimed["revision"] + 1,
                "profile": built.to_dict(),
                "lease": None,
            }
            if await self._store.compare_and_set_state(
                key, published, expected_revision=claimed["revision"]
            ):
                return built
            return None
        except Exception:
            released = {**claimed, "revision": claimed["revision"] + 1, "lease": None}
            await self._store.compare_and_set_state(
                key, released, expected_revision=claimed["revision"]
            )
            raise
