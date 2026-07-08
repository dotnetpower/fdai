"""In-memory :class:`IdempotencyStore` for tests and single-replica dev.

Mirrors the durable Postgres backend's semantics (atomic first-writer
wins) without I/O. Not persistent - a restart forgets recorded keys, so
this is only correct for a single replica; multi-replica or
restart-durable deployments wire the Postgres backend.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


class InMemoryIdempotencyStore:
    """Dict-backed :class:`IdempotencyStore`."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def seen(self, key: str) -> Mapping[str, Any] | None:
        value = self._store.get(key)
        return deepcopy(value) if value is not None else None

    async def record(self, key: str, result: Mapping[str, Any]) -> bool:
        if key in self._store:
            return False
        self._store[key] = deepcopy(dict(result))
        return True


__all__ = ["InMemoryIdempotencyStore"]
