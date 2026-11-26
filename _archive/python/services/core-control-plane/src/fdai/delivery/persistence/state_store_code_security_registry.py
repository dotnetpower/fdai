"""State-store-backed remediation-pack registry for multi-host installations.

Each pack is one ``state_kv`` row keyed ``runtime:code-security-pack:<pack_id>`` holding FDAI's
authoritative record (manifest digest, base commit, issue membership, expiry, revocation) and an
append-only, bounded review log. Updates use revision compare-and-set, so concurrent revocations
and reviews never overwrite each other. The export baseline lives in a separate row because it
holds issue locations that the Operator read view must never expose.
"""

from __future__ import annotations

import os
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, TypeVar

from fdai.core.security.code_findings.result_import import PackRecord
from fdai.shared.providers.remediation_pack import PackRegistryError
from fdai.shared.providers.state_store import StateStore

PACK_STATE_PREFIX = "runtime:code-security-pack:"
BASELINE_STATE_PREFIX = "runtime:code-security-pack-baseline:"
MAX_REVIEWS = 500
_MAX_CAS_ATTEMPTS = 8
_MAX_LIST = 1000
_PACK_ID = re.compile(r"^[0-9a-f]{12}$")
_T = TypeVar("_T")


def _pack_id(pack_id: str) -> str:
    if _PACK_ID.fullmatch(pack_id) is None:
        raise PackRegistryError("pack id must be 12 lowercase hex characters")
    return pack_id


def _record(document: Mapping[str, Any]) -> PackRecord:
    try:
        return PackRecord(
            pack_id=str(document["pack_id"]),
            manifest_sha256=str(document["manifest_sha256"]),
            base_commit=str(document["base_commit"]),
            issue_ids=frozenset(str(i) for i in document["issue_ids"]),
            expires_at=datetime.fromisoformat(str(document["expires_at"])),
            revoked=bool(document.get("revoked", False)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PackRegistryError("pack record is missing required fields") from exc


class StateStoreRemediationPackRegistry:
    """Implement :class:`RemediationPackRegistry` over an injected :class:`StateStore`."""

    def __init__(self, store: StateStore, clock: Callable[[], datetime] | None = None) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    async def _read(self, pack_id: str) -> dict[str, Any] | None:
        row = await self._store.read_state(PACK_STATE_PREFIX + _pack_id(pack_id))
        return None if row is None else dict(row)

    async def _update(self, pack_id: str, change: Callable[[dict[str, Any]], None]) -> PackRecord:
        for _ in range(_MAX_CAS_ATTEMPTS):
            document = await self._read(pack_id)
            if document is None:
                raise PackRegistryError(f"pack {pack_id} is not recorded")
            revision = int(document.get("revision", 0))
            change(document)
            document["revision"] = revision + 1
            if await self._store.compare_and_set_state(
                PACK_STATE_PREFIX + pack_id, document, expected_revision=revision
            ):
                return _record(document)
        raise PackRegistryError(f"pack {pack_id} changed concurrently; retry later")

    async def record(self, pack: PackRecord) -> None:
        created = await self._store.write_state_if_absent(
            PACK_STATE_PREFIX + _pack_id(pack.pack_id),
            {
                "pack_id": pack.pack_id,
                "manifest_sha256": pack.manifest_sha256,
                "base_commit": pack.base_commit,
                "issue_ids": sorted(pack.issue_ids),
                "expires_at": pack.expires_at.isoformat(),
                "revoked": pack.revoked,
                "recorded_at": self._clock().isoformat(),
                "reviews": [],
                "revision": 1,
            },
        )
        if not created:
            raise PackRegistryError(f"pack {pack.pack_id} is already recorded")

    async def get(self, pack_id: str) -> PackRecord | None:
        document = await self._read(pack_id)
        return None if document is None else _record(document)

    async def revoke(self, pack_id: str, reason: str) -> PackRecord:
        def change(document: dict[str, Any]) -> None:
            document.update(
                revoked=True,
                revoked_at=self._clock().isoformat(),
                revocation_reason=reason[:500],
            )

        return await self._update(pack_id, change)

    async def list_active(self) -> Sequence[PackRecord]:
        now = self._clock()
        rows = await self._store.read_states(PACK_STATE_PREFIX, limit=_MAX_LIST)
        records = [_record(row) for row in rows]
        return sorted(
            (r for r in records if not r.revoked and now <= r.expires_at), key=lambda r: r.pack_id
        )

    async def record_baseline(self, pack_id: str, document: Mapping[str, Any]) -> None:
        if not await self._store.write_state_if_absent(
            BASELINE_STATE_PREFIX + _pack_id(pack_id), dict(document)
        ):
            raise PackRegistryError(f"pack {pack_id} already has a baseline")

    async def get_baseline(self, pack_id: str) -> Mapping[str, Any] | None:
        return await self._store.read_state(BASELINE_STATE_PREFIX + _pack_id(pack_id))

    async def append_review(self, pack_id: str, document: Mapping[str, Any]) -> None:
        entry = {**document, "recorded_at": self._clock().isoformat()}

        def change(current: dict[str, Any]) -> None:
            reviews = list(current.get("reviews", []))
            if len(reviews) >= MAX_REVIEWS:
                raise PackRegistryError(f"pack {pack_id} review log is full")
            current["reviews"] = [*reviews, entry]

        await self._update(pack_id, change)

    async def list_reviews(self, pack_id: str) -> Sequence[Mapping[str, Any]]:
        document = await self._read(pack_id)
        return [] if document is None else list(document.get("reviews", []))


class _PerCallPostgresStore:
    """Open one PostgreSQL state store per call so synchronous CLI steps can each own a loop."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def _call(self, operation: Callable[[StateStore], Awaitable[_T]]) -> _T:
        from fdai.delivery.persistence.postgres import (
            PostgresStateStore,
            PostgresStateStoreConfig,
        )

        store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=self._dsn))
        try:
            return await operation(store)
        finally:
            await store.aclose()

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        return await self._call(lambda store: store.read_state(key))

    async def write_state_if_absent(self, key: str, value: Mapping[str, Any]) -> bool:
        return await self._call(lambda store: store.write_state_if_absent(key, value))

    async def compare_and_set_state(
        self, key: str, value: Mapping[str, Any], *, expected_revision: int
    ) -> bool:
        return await self._call(
            lambda store: store.compare_and_set_state(
                key, value, expected_revision=expected_revision
            )
        )

    async def read_states(self, prefix: str, *, limit: int) -> tuple[Mapping[str, Any], ...]:
        return await self._call(lambda store: store.read_states(prefix, limit=limit))


STATE_STORE_REGISTRY = "state-store"
"""``--registry`` value that selects the state store named by ``FDAI_STATE_STORE_DSN``."""


def open_pack_registry(spec: str) -> Any:
    """Return the file registry for a directory, or the state-store registry for ``state-store``.

    The database location comes from the environment only, never from arguments.
    """
    if spec != STATE_STORE_REGISTRY:
        from pathlib import Path

        from fdai.delivery.code_security_registry import FileRemediationPackRegistry

        return FileRemediationPackRegistry(Path(spec))
    dsn = (
        os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
        or os.environ.get("FDAI_DATABASE_URL", "").strip()
    )
    if not dsn:
        raise ValueError("--registry state-store requires FDAI_STATE_STORE_DSN in the environment")
    return StateStoreRemediationPackRegistry(_PerCallPostgresStore(dsn))  # type: ignore[arg-type]


__all__ = [
    "BASELINE_STATE_PREFIX",
    "MAX_REVIEWS",
    "PACK_STATE_PREFIX",
    "STATE_STORE_REGISTRY",
    "StateStoreRemediationPackRegistry",
    "open_pack_registry",
]
