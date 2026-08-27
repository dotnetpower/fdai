"""Bounded Kubernetes lifecycle collector: durable cursor plus append-only evidence."""

from __future__ import annotations

from dataclasses import dataclass
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


class KubernetesLifecycleStore(Protocol):
    """Persist durable cursor progress and append-only lifecycle evidence."""

    async def read_cursor(self, cluster_ref: str) -> str | None: ...

    async def append(
        self,
        *,
        cluster_ref: str,
        previous_cursor: str | None,
        next_cursor: str | None,
        observations: tuple[KubernetesLifecycleObservation, ...],
    ) -> KubernetesLifecycleAppendReceipt: ...


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
    cursor_changed = poll.next_cursor != previous_cursor
    if poll.observations or cursor_changed:
        receipt = await store.append(
            cluster_ref=cluster_ref,
            previous_cursor=previous_cursor,
            next_cursor=poll.next_cursor,
            observations=poll.observations,
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
    return KubernetesLifecycleCollectionReceipt(
        cluster_ref=cluster_ref,
        polled_count=0,
        inserted_count=0,
        duplicate_count=0,
        complete=poll.complete,
        limitation=poll.limitation,
        cursor=previous_cursor,
    )


__all__ = [
    "KubernetesLifecycleAppendReceipt",
    "KubernetesLifecycleCollectionReceipt",
    "KubernetesLifecycleCursorConflictError",
    "KubernetesLifecycleStore",
    "collect_kubernetes_lifecycle_once",
]
