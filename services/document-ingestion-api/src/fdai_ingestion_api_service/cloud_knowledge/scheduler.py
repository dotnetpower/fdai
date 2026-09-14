"""Short bounded due sweeps over durable per-source leases; no live query polling."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from fdai_service_contracts.cloud_knowledge import SourceRegistryRevision

from fdai_ingestion_api_service.cloud_knowledge.collector import (
    CloudDocumentCollector,
    SourceState,
    source_due,
)
from fdai_ingestion_api_service.cloud_knowledge.store import SourceCheckpoint


class SourceCheckpointStore(Protocol):
    async def get(self, registry_digest: str, source_id: str) -> SourceCheckpoint: ...

    async def claim(self, registry_digest: str, source_id: str, revision: int) -> UUID | None: ...

    async def finish(
        self,
        registry_digest: str,
        source_id: str,
        checkpoint: SourceCheckpoint,
        claim: UUID,
        state: SourceState,
    ) -> None: ...


class CloudKnowledgeScheduler:
    """One sweep can resume after process loss without publishing partial knowledge."""

    def __init__(
        self,
        *,
        registry: SourceRegistryRevision,
        store: SourceCheckpointStore,
        collector: CloudDocumentCollector,
        clock: Callable[[], datetime],
    ) -> None:
        self.registry = registry
        self._store = store
        self._collector = collector
        self._clock = clock

    async def tick(self) -> dict[str, int | str]:
        """Run at startup or on a scheduled tick; stop on provider pressure or timeout."""
        counters: dict[str, int | str] = {"checked": 0, "failed": 0, "status": "complete"}
        if self._clock() >= self.registry.valid_until:
            return {**counters, "status": "registry_expired"}
        try:
            async with asyncio.timeout(900):
                for source in self.registry.sources:
                    now = self._clock()
                    if now >= self.registry.valid_until:
                        counters["status"] = "registry_expired"
                        break
                    checkpoint = await self._store.get(self.registry.digest, source.source_id)
                    if not source_due(source, checkpoint.state, now):
                        continue
                    claim = await self._store.claim(
                        self.registry.digest,
                        source.source_id,
                        checkpoint.revision,
                    )
                    if claim is None:
                        continue
                    async with asyncio.timeout(120):
                        state = await self._collector.collect(source, checkpoint.state, now=now)
                        await self._store.finish(
                            self.registry.digest,
                            source.source_id,
                            checkpoint,
                            claim,
                            state,
                        )
                    counters["checked"] = int(counters["checked"]) + 1
                    if state.last_attempt and state.last_attempt.outcome in {
                        "failed",
                        "withdrawal_pending",
                    }:
                        counters["failed"] = int(counters["failed"]) + 1
                        counters["status"] = "partial"
                        if state.last_attempt.reason in {"http_429", "http_503"}:
                            break
        except TimeoutError:
            counters["status"] = "deadline_exceeded"
        return counters
