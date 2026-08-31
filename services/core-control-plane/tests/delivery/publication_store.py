"""In-memory compare-and-set store for durable publication ledger tests.

Analyzer publication safety is a property of the durable record transitions,
not of a mock's return values. Every test that needs a ledger therefore drives
the real :class:`PostgresAnalyzerPublicationLedger` over this store, so a crash
is modelled by dropping the process and re-reading the same records.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


class ConditionalStore:
    """Compare-and-set key/value store with the idempotency-store contract."""

    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}

    async def seen(self, key: str) -> Mapping[str, Any] | None:
        value = self.values.get(key)
        return deepcopy(value) if value is not None else None

    async def record(self, key: str, result: Mapping[str, Any]) -> bool:
        if key in self.values:
            return False
        self.values[key] = dict(result)
        return True

    async def remove_if(self, key: str, expected: Mapping[str, Any]) -> bool:
        if self.values.get(key) != expected:
            return False
        del self.values[key]
        return True

    async def insert_or_replace_if(
        self,
        key: str,
        expected: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> bool:
        current = self.values.get(key)
        if current is None:
            self.values[key] = dict(result)
            return True
        if current != expected and current != result:
            return False
        self.values[key] = dict(result)
        return True


__all__ = ["ConditionalStore"]
