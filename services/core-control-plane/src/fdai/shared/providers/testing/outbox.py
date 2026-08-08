"""In-memory :class:`OutboxStore` for tests and single-replica dev."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from fdai.shared.providers.outbox import OutboxClaim, OutboxStatus


class InMemoryOutboxStore:
    """Dict-backed outbox mirroring the Postgres backend's semantics."""

    def __init__(self) -> None:
        # key -> {"status": OutboxStatus, "result": dict | None}
        self._rows: dict[str, dict[str, Any]] = {}

    async def claim(self, key: str) -> OutboxClaim:
        row = self._rows.get(key)
        if row is None:
            self._rows[key] = {"status": OutboxStatus.IN_PROGRESS, "result": None}
            return OutboxClaim(status=OutboxStatus.NEW)
        if row["status"] == OutboxStatus.DONE:
            result = row["result"]
            return OutboxClaim(
                status=OutboxStatus.DONE,
                result=deepcopy(result) if result is not None else None,
            )
        return OutboxClaim(status=OutboxStatus.IN_PROGRESS)

    async def complete(self, key: str, result: Mapping[str, Any]) -> None:
        row = self._rows.get(key)
        # Freeze terminal rows: a duplicate ``complete()`` on an already-DONE
        # key MUST NOT overwrite the recorded outcome. Mirrors the Postgres
        # backend's ``WHERE action_outbox.status <> 'done'`` guard.
        if row is not None and row["status"] == OutboxStatus.DONE:
            return
        self._rows[key] = {
            "status": OutboxStatus.DONE,
            "result": deepcopy(dict(result)),
        }


__all__ = ["InMemoryOutboxStore"]
