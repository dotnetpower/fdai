"""Bounded Kubernetes lifecycle collector: durable cursor plus append-only evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.core.ontology_platform.kubernetes_lifecycle_observation import (
    KubernetesLifecycleObservation,
)
from fdai.delivery.kubernetes_lifecycle_source import (
    KubernetesLifecyclePoll,
    KubernetesLifecycleSource,
)


class KubernetesLifecycleCursorConflictError(RuntimeError):
    """Report that the durable cursor moved concurrently under another writer."""


@dataclass(frozen=True, slots=True)
class KubernetesLifecycleAppendReceipt:
    """Durable outcome of one atomic cursor-plus-observation append."""

    cluster_ref: str
    inserted_count: int
    duplicate_count: int
    cursor: str | None


@dataclass(frozen=True, slots=True)
class KubernetesLifecycleCursorState:
    """Durable cursor plus the collector heartbeat that established it."""

    resource_version: str | None
    updated_at: datetime
    complete: bool = True
    limitation: str | None = None


@dataclass(frozen=True, slots=True)
class KubernetesLifecycleReadSnapshot:
    """Consistent cursor and retained-observation view from one database snapshot."""

    state: KubernetesLifecycleCursorState | None
    observations: tuple[KubernetesLifecycleObservation, ...]


class KubernetesLifecycleStore(Protocol):
    """Persist durable cursor progress and append-only lifecycle evidence."""

    async def read_cursor(self, cluster_ref: str) -> str | None: ...

    async def read_cursor_state(
        self, cluster_ref: str
    ) -> KubernetesLifecycleCursorState | None: ...

    async def append(
        self,
        *,
        cluster_ref: str,
        previous_cursor: str | None,
        next_cursor: str | None,
        observations: tuple[KubernetesLifecycleObservation, ...],
        complete: bool = True,
        limitation: str | None = None,
    ) -> KubernetesLifecycleAppendReceipt: ...

    async def read_observations(
        self,
        *,
        cluster_ref: str,
        object_uids: tuple[str, ...],
        start: datetime,
        end: datetime,
        limit: int,
    ) -> tuple[KubernetesLifecycleObservation, ...]: ...

    async def read_snapshot(
        self,
        *,
        cluster_ref: str,
        object_uids: tuple[str, ...],
        start: datetime,
        end: datetime,
        limit: int,
    ) -> KubernetesLifecycleReadSnapshot: ...


@dataclass(frozen=True, slots=True)
class KubernetesLifecycleCollectionReceipt:
    """Report one bounded collector pass without provider payload content."""

    cluster_ref: str
    polled_count: int
    inserted_count: int
    duplicate_count: int
    complete: bool
    limitation: str | None
    cursor: str | None


async def collect_kubernetes_lifecycle_once(
    *,
    source: KubernetesLifecycleSource,
    store: KubernetesLifecycleStore,
    cluster_ref: str,
) -> KubernetesLifecycleCollectionReceipt:
    """Poll one bounded slice and append it durably; never mutate ontology instances.

    The store is the single writer of record: it verifies `previous_cursor` still
    matches the durable value before admitting new observations and advancing the
    cursor, so a concurrent collector run cannot silently move state backward or lose
    a duplicate/reordered delivery. A cursor-expiry gap resets the durable cursor to
    `None` (a real, explicit coverage gap) rather than silently continuing.
    """

    previous_cursor = await store.read_cursor(cluster_ref)
    poll: KubernetesLifecyclePoll = await source.poll(
        cluster_ref=cluster_ref, cursor=previous_cursor
    )
    if poll.cluster_ref != cluster_ref:
        raise ValueError("Kubernetes lifecycle source responded with a foreign cluster_ref")
    next_cursor = (
        poll.next_cursor
        if poll.complete or poll.cursor_safe or poll.limitation == "cursor_expired"
        else previous_cursor
    )
    receipt = await store.append(
        cluster_ref=cluster_ref,
        previous_cursor=previous_cursor,
        next_cursor=next_cursor,
        observations=poll.observations,
        complete=poll.complete,
        limitation=poll.limitation,
    )
    return KubernetesLifecycleCollectionReceipt(
        cluster_ref=cluster_ref,
        polled_count=len(poll.observations),
        inserted_count=receipt.inserted_count,
        duplicate_count=receipt.duplicate_count,
        complete=poll.complete,
        limitation=poll.limitation,
        cursor=receipt.cursor,
    )


__all__ = [
    "KubernetesLifecycleAppendReceipt",
    "KubernetesLifecycleCollectionReceipt",
    "KubernetesLifecycleCursorState",
    "KubernetesLifecycleReadSnapshot",
    "KubernetesLifecycleCursorConflictError",
    "KubernetesLifecycleStore",
    "collect_kubernetes_lifecycle_once",
]
