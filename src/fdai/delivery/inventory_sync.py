"""Fail-closed full-snapshot coordinator with ordered source fallback."""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import cast

import httpx

from fdai.shared.providers.inventory import Inventory, InventoryBatch
from fdai.shared.providers.inventory_snapshot import (
    InventoryAttemptFailure,
    InventoryCoverageManifest,
    InventoryFailureCode,
    InventorySnapshotStore,
    InventorySource,
    InventorySourcesExhaustedError,
    InventorySyncResult,
)


class InventoryStreamError(RuntimeError):
    """An inventory stream violated its atomic-fence contract."""


class InventorySyncCoordinator:
    """Stage one source at a time and promote only a complete stream."""

    def __init__(self, *, store: InventorySnapshotStore) -> None:
        self._store = store

    async def run(self, sources: Sequence[InventorySource]) -> InventorySyncResult:
        if not sources:
            raise ValueError("sources MUST NOT be empty")
        failures: list[InventoryAttemptFailure] = []
        for source in sources:
            attempt_id = await self._store.begin(source.manifest)
            try:
                completed = await self._stage_stream(
                    attempt_id,
                    cast(Inventory, source.inventory).full_snapshot(),
                )
                manifest = InventoryCoverageManifest(
                    source=source.manifest.source,
                    scopes=source.manifest.scopes,
                    resource_types=source.manifest.resource_types,
                    observation_kind=source.manifest.observation_kind,
                    started_at=source.manifest.started_at,
                    completed_at=completed,
                    metadata=source.manifest.metadata,
                )
                await self._store.promote(attempt_id, manifest)
            except Exception as exc:  # noqa: BLE001 - source boundary, classified and retained
                failure = classify_inventory_failure(exc)
                await self._store.fail(attempt_id, failure)
                failures.append(failure)
                continue
            return InventorySyncResult(
                attempt_id=attempt_id,
                source=source.name,
                failures=tuple(failures),
            )
        raise InventorySourcesExhaustedError(failures)

    async def _stage_stream(
        self,
        attempt_id: str,
        stream: AsyncIterator[InventoryBatch],
    ) -> datetime:
        saw_final = False
        async for batch in stream:
            if saw_final:
                raise InventoryStreamError("inventory stream emitted data after final fence")
            if batch.final:
                saw_final = True
            if batch.resources or batch.links:
                await self._store.stage(
                    attempt_id,
                    InventoryBatch(
                        resources=batch.resources,
                        links=batch.links,
                        cursor=batch.cursor,
                    ),
                )
        if not saw_final:
            raise InventoryStreamError("inventory stream ended before final fence")
        return datetime.now(tz=UTC)


def classify_inventory_failure(exc: Exception) -> InventoryAttemptFailure:
    """Map transport and contract failures to a bounded, secret-free code."""

    message = type(exc).__name__
    code = InventoryFailureCode.SOURCE_UNAVAILABLE
    if isinstance(exc, InventoryStreamError):
        code = InventoryFailureCode.PARTIAL
        message = str(exc)
    elif isinstance(exc, (httpx.ConnectTimeout, httpx.ConnectError)):
        cause = exc.__cause__
        code = (
            InventoryFailureCode.DNS_FAILED
            if isinstance(cause, socket.gaierror)
            else InventoryFailureCode.NETWORK_BLOCKED
        )
    else:
        text = str(exc).lower()
        if "http 401" in text or "token" in text or "identity" in text:
            code = InventoryFailureCode.TOKEN_FAILED
        elif "http 403" in text or "forbidden" in text:
            code = InventoryFailureCode.FORBIDDEN
        elif "http 429" in text or "throttl" in text:
            code = InventoryFailureCode.THROTTLED
        elif "pagination cap" in text or "partial" in text:
            code = InventoryFailureCode.PARTIAL
        elif isinstance(exc, (ValueError, TypeError)):
            code = InventoryFailureCode.INVALID_DATA
    return InventoryAttemptFailure(code=code, message=message[:200])


__all__ = [
    "InventoryStreamError",
    "InventorySyncCoordinator",
    "classify_inventory_failure",
]
