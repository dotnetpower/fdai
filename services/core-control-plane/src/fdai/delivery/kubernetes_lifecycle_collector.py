"""Bounded Kubernetes lifecycle collector: durable cursor plus append-only evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.core.ontology_platform.kubernetes_lifecycle_observation import (
    KubernetesLifecycleObservation,
    KubernetesPodLifecycleIdentity,
)
from fdai.delivery.kubernetes_lifecycle_source import (
    MAX_KUBERNETES_LIFECYCLE_POLL_OBSERVATIONS,
    KubernetesLifecyclePoll,
    KubernetesLifecycleSource,
)

_MAX_OBSERVATIONS_PER_APPEND = MAX_KUBERNETES_LIFECYCLE_POLL_OBSERVATIONS


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
    list_continue_token: str | None = None
    coverage_started_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.resource_version is not None and self.list_continue_token is not None:
            raise ValueError("Kubernetes lifecycle state MUST NOT mix watch and LIST cursors")
        if self.list_continue_token is not None and not (
            0 < len(self.list_continue_token) <= 2_048
        ):
            raise ValueError("Kubernetes lifecycle LIST cursor MUST be bounded non-empty")
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("Kubernetes lifecycle state update time MUST be timezone-aware")
        if self.coverage_started_at is not None and (
            self.coverage_started_at.tzinfo is None
            or self.coverage_started_at.utcoffset() is None
            or self.coverage_started_at > self.updated_at
        ):
            raise ValueError("Kubernetes lifecycle coverage boundary is invalid")


@dataclass(frozen=True, slots=True)
class KubernetesLifecycleReadSnapshot:
    """Consistent cursor and retained-observation view from one database snapshot."""

    state: KubernetesLifecycleCursorState | None
    observations: tuple[KubernetesLifecycleObservation, ...]


@dataclass(frozen=True, slots=True)
class KubernetesPodLifecycleCohortSnapshot:
    """Consistent collector state, Pod identities, and exact-UID lifecycle rows."""

    state: KubernetesLifecycleCursorState | None
    identities: tuple[KubernetesPodLifecycleIdentity, ...]
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
        previous_list_continue_token: str | None,
        next_cursor: str | None,
        next_list_continue_token: str | None,
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
        namespace: str | None = None,
        owner_uid: str | None = None,
    ) -> tuple[KubernetesLifecycleObservation, ...]: ...

    async def read_snapshot(
        self,
        *,
        cluster_ref: str,
        object_uids: tuple[str, ...],
        start: datetime,
        end: datetime,
        limit: int,
        namespace: str | None = None,
        owner_uid: str | None = None,
    ) -> KubernetesLifecycleReadSnapshot: ...

    async def append_pod_identities(
        self,
        identities: tuple[KubernetesPodLifecycleIdentity, ...],
    ) -> None: ...

    async def read_pod_lifecycle_cohort(
        self,
        *,
        cluster_ref: str,
        namespace: str,
        root_controller_uid: str,
        start: datetime,
        end: datetime,
        identity_limit: int,
        event_limit: int,
    ) -> KubernetesPodLifecycleCohortSnapshot: ...


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

    previous_state = await store.read_cursor_state(cluster_ref)
    previous_cursor = None if previous_state is None else previous_state.resource_version
    previous_list_continue_token = (
        None if previous_state is None else previous_state.list_continue_token
    )
    poll: KubernetesLifecyclePoll = await source.poll(
        cluster_ref=cluster_ref,
        cursor=previous_cursor,
        list_continue_token=previous_list_continue_token,
    )
    if poll.cluster_ref != cluster_ref:
        raise ValueError("Kubernetes lifecycle source responded with a foreign cluster_ref")
    may_advance = poll.complete or poll.cursor_safe or poll.limitation == "cursor_expired"
    next_cursor = poll.next_cursor if may_advance else previous_cursor
    next_list_continue_token = (
        poll.next_list_continue_token if may_advance else previous_list_continue_token
    )
    receipt = await store.append(
        cluster_ref=cluster_ref,
        previous_cursor=previous_cursor,
        previous_list_continue_token=previous_list_continue_token,
        next_cursor=next_cursor,
        next_list_continue_token=next_list_continue_token,
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
    "KubernetesPodLifecycleCohortSnapshot",
    "KubernetesLifecycleCursorConflictError",
    "KubernetesLifecycleStore",
    "collect_kubernetes_lifecycle_once",
]
