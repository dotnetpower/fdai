"""Narrow provider ports consumed by the isolated Executor service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class ExecutorStateStore(Protocol):
    """Persist executor audit records and atomic durable attempt claims."""

    async def append_audit_entry(self, entry: Mapping[str, Any]) -> None: ...

    async def read_state(self, key: str) -> Mapping[str, Any] | None: ...

    async def write_state_with_audit_if_absent(
        self,
        key: str,
        value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool: ...


__all__ = ["ExecutorStateStore"]
