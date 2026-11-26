"""Bounded read coalescing for one Pod analyzer tick, including failed reads."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Hashable, Mapping
from dataclasses import replace
from datetime import datetime
from types import MappingProxyType
from typing import Any, TypeVar, cast

from fdai.core.ontology_platform.kubernetes_lifecycle import (
    KubernetesLifecycleCoverageSegment,
    KubernetesLifecycleCursor,
    KubernetesLifecycleObservation,
)
from fdai.delivery.kubernetes_api_inventory import (
    KubernetesApiInventorySnapshot,
    KubernetesApiInventorySource,
)
from fdai.delivery.kubernetes_pod_observations import PodEvidenceUnavailableError
from fdai.delivery.persistence.postgres_kubernetes_lifecycle import PostgresKubernetesLifecycleStore
from fdai.shared.providers.inventory import (
    PromotedInventoryGeneration,
    PromotedInventoryGenerationReader,
    ResourceRecord,
)

_T = TypeVar("_T")


class PodTickCache:
    """Pin reads to one source instance; neither failures nor cancellation trigger retries."""

    def __init__(self, *, timeout_seconds: float) -> None:
        self._timeout = timeout_seconds
        self._tasks: dict[Hashable, asyncio.Task[Any]] = {}
        self._values: dict[Hashable, object] = {}
        self._closed = False

    async def read(self, key: Hashable, loader: Callable[[], Awaitable[_T]]) -> _T:
        self._admit(key, self._tasks)
        if key not in self._tasks:

            async def bounded() -> _T:
                async with asyncio.timeout(self._timeout):
                    return await loader()

            self._tasks[key] = asyncio.create_task(bounded())
        # A cancelled/expired target must not cancel another target's shared read.
        return cast(_T, await asyncio.shield(self._tasks[key]))

    def once(self, key: Hashable, loader: Callable[[], _T]) -> _T:
        self._admit(key, self._values)
        if key not in self._values:
            self._values[key] = loader()
        return cast(_T, self._values[key])

    def _admit(self, key: Hashable, entries: Mapping[Hashable, object]) -> None:
        if self._closed:
            raise PodEvidenceUnavailableError("pod_tick_source_closed")
        if key not in entries and len(entries) >= 2_000:
            raise PodEvidenceUnavailableError("pod_tick_cache_limit", status="partial")

    async def aclose(self) -> None:
        self._closed = True
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)


async def read_inventory(
    inventory: PromotedInventoryGenerationReader, *, max_resources: int
) -> PromotedInventoryGeneration | None:
    generation = await inventory.load_active_generation(max_resources=max_resources)
    return (
        replace(generation, resources=tuple(_freeze_record(row) for row in generation.resources))
        if generation is not None
        else None
    )


async def collect_snapshot(
    collector: KubernetesApiInventorySource,
) -> KubernetesApiInventorySnapshot:
    snapshot = await collector.collect()
    return replace(snapshot, resources=tuple(_freeze_record(row) for row in snapshot.resources))


def _freeze_record(record: ResourceRecord) -> ResourceRecord:
    return replace(record, props=_freeze(record.props))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


class PodTickHistoryStore:
    """Share cursor/coverage reads and retain exact UID event scopes, never cluster-wide events."""

    def __init__(self, store: PostgresKubernetesLifecycleStore, cache: PodTickCache) -> None:
        self._store = store
        self._cache = cache

    def as_reader_store(self) -> PostgresKubernetesLifecycleStore:
        # The existing durable reader uses only the three read methods below.
        return cast(PostgresKubernetesLifecycleStore, self)

    async def read_cursor(self, cluster_ref: str) -> KubernetesLifecycleCursor | None:
        return await self._cache.read(
            ("history-cursor", cluster_ref), lambda: self._store.read_cursor(cluster_ref)
        )

    async def read_observations(
        self,
        *,
        cluster_ref: str,
        object_uid: str | None,
        since: datetime,
        limit: int = 257,
    ) -> tuple[KubernetesLifecycleObservation, ...]:
        if object_uid is None:
            raise PodEvidenceUnavailableError("pod_history_uid_unbound")
        return await self._cache.read(
            ("history-uid", cluster_ref, object_uid, since, limit),
            lambda: self._store.read_observations(
                cluster_ref=cluster_ref, object_uid=object_uid, since=since, limit=limit
            ),
        )

    async def read_incomplete_coverage_segments(
        self,
        *,
        cluster_ref: str,
        since: datetime,
        through: datetime,
        limit: int = 257,
    ) -> tuple[KubernetesLifecycleCoverageSegment, ...]:
        return await self._cache.read(
            ("history-coverage", cluster_ref, since, through, limit),
            lambda: self._store.read_incomplete_coverage_segments(
                cluster_ref=cluster_ref, since=since, through=through, limit=limit
            ),
        )
