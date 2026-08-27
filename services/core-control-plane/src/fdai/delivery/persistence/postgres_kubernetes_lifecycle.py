"""PostgreSQL atomic cursor-plus-append-only persistence for Kubernetes lifecycle evidence."""

# ruff: noqa: S608 - table and column identifiers are fixed private call-site literals.

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.core.ontology_platform.kubernetes_lifecycle_observation import (
    KubernetesLifecycleObservation,
    KubernetesPodLifecycleIdentity,
)
from fdai.delivery.kubernetes_lifecycle_collector import (
    KubernetesLifecycleAppendReceipt,
    KubernetesLifecycleCursorConflictError,
    KubernetesLifecycleCursorState,
    KubernetesLifecycleReadSnapshot,
    KubernetesPodLifecycleCohortSnapshot,
)
from fdai.delivery.kubernetes_lifecycle_source import (
    MAX_KUBERNETES_LIFECYCLE_POLL_OBSERVATIONS,
)

_MAX_OBSERVATIONS_PER_APPEND: Final = MAX_KUBERNETES_LIFECYCLE_POLL_OBSERVATIONS


@dataclass(frozen=True, slots=True)
class PostgresKubernetesLifecycleStoreConfig:
    """Configure bounded PostgreSQL Kubernetes lifecycle evidence access."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("Kubernetes lifecycle store DSN MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("Kubernetes lifecycle store timeouts MUST be positive")


class PostgresKubernetesLifecycleStore:
    """Persist the durable resumption cursor and append-only lifecycle observations.

    Every `append` call verifies the durable cursor still equals `previous_cursor` and
    then, in one transaction, inserts new observations idempotently (duplicate and
    reordered deliveries are rejected by their content-addressed `evidence_ref`) and
    advances (or, on an explicit cursor-expiry gap, clears) the cursor. The
    observation table itself only ever accepts inserts; it is never updated or
    deleted by this store, and its append-only trigger enforces that durably.
    """

    def __init__(
        self,
        *,
        config: PostgresKubernetesLifecycleStoreConfig,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._now: Final = now or (lambda: datetime.now(UTC))

    async def read_cursor(self, cluster_ref: str) -> str | None:
        """Return the durable resumption cursor, or `None` when never collected."""

        state = await self.read_cursor_state(cluster_ref)
        return None if state is None else state.resource_version

    async def read_cursor_state(self, cluster_ref: str) -> KubernetesLifecycleCursorState | None:
        """Return the cursor and its last collector update time."""

        async with await self._connect() as connection:
            await self._set_timeout(connection)
            await self._lock_cluster(connection, cluster_ref)
            cursor = await connection.execute(
                "SELECT resource_version, updated_at, complete, limitation "
                "FROM kubernetes_lifecycle_cursor "
                "WHERE cluster_ref = %s",
                (cluster_ref,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return KubernetesLifecycleCursorState(
            resource_version=(
                None if row["resource_version"] is None else str(row["resource_version"])
            ),
            updated_at=row["updated_at"],
            complete=bool(row["complete"]),
            limitation=None if row["limitation"] is None else str(row["limitation"]),
        )

    async def append(
        self,
        *,
        cluster_ref: str,
        previous_cursor: str | None,
        next_cursor: str | None,
        observations: tuple[KubernetesLifecycleObservation, ...],
        complete: bool = True,
        limitation: str | None = None,
    ) -> KubernetesLifecycleAppendReceipt:
        """Atomically admit new observations and advance the durable cursor.

        Raises `KubernetesLifecycleCursorConflictError` when the durable cursor no longer
        equals `previous_cursor`, which means a concurrent writer already advanced it;
        the caller MUST NOT retry blindly and instead re-read the current cursor.
        """

        if len(observations) > _MAX_OBSERVATIONS_PER_APPEND:
            raise ValueError("Kubernetes lifecycle append exceeds its observation bound")
        if any(item.cluster_ref != cluster_ref for item in observations):
            raise ValueError("Kubernetes lifecycle append widened the requested cluster scope")
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            await self._lock_cluster(connection, cluster_ref)
            locked = await connection.execute(
                "SELECT resource_version FROM kubernetes_lifecycle_cursor "
                "WHERE cluster_ref = %s FOR UPDATE",
                (cluster_ref,),
            )
            row = await locked.fetchone()
            current_cursor = (
                None
                if row is None or row["resource_version"] is None
                else str(row["resource_version"])
            )
            if current_cursor != previous_cursor:
                raise KubernetesLifecycleCursorConflictError(
                    "Kubernetes lifecycle cursor moved concurrently under another writer"
                )
            inserted = 0
            duplicate = 0
            for observation in observations:
                created = await connection.execute(
                    "INSERT INTO kubernetes_lifecycle_observation ("
                    "evidence_ref, cluster_ref, namespace, object_uid, owner_uid, reason, "
                    "category, event_type, event_time, recorded_time, source_revision, record"
                    ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (evidence_ref) DO NOTHING RETURNING evidence_ref",
                    (
                        observation.evidence_ref,
                        observation.cluster_ref,
                        observation.namespace,
                        observation.object_uid,
                        observation.owner_uid,
                        observation.reason,
                        observation.category,
                        observation.event_type,
                        observation.event_time,
                        observation.recorded_time,
                        observation.source_revision,
                        Jsonb(_record(observation)),
                    ),
                )
                if await created.fetchone() is not None:
                    inserted += 1
                else:
                    duplicate += 1
            await connection.execute(
                "INSERT INTO kubernetes_lifecycle_cursor "
                "(cluster_ref, resource_version, updated_at, complete, limitation) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (cluster_ref) DO UPDATE SET "
                "resource_version = excluded.resource_version, "
                "updated_at = excluded.updated_at, "
                "complete = excluded.complete, limitation = excluded.limitation",
                (cluster_ref, next_cursor, self._now(), complete, limitation),
            )
        return KubernetesLifecycleAppendReceipt(
            cluster_ref=cluster_ref,
            inserted_count=inserted,
            duplicate_count=duplicate,
            cursor=next_cursor,
        )

    async def read_observations(
        self,
        *,
        cluster_ref: str,
        object_uids: tuple[str, ...],
        start: datetime,
        end: datetime,
        limit: int = _MAX_OBSERVATIONS_PER_APPEND,
        namespace: str | None = None,
        owner_uid: str | None = None,
    ) -> tuple[KubernetesLifecycleObservation, ...]:
        """Read retained lifecycle observations without changing the append-only store.

        An empty result is deliberately not interpreted as proof that no lifecycle event
        occurred. Callers must combine this read with the durable cursor and collection
        completeness before presenting a historical absence.
        """

        if not cluster_ref.strip() or not object_uids:
            raise ValueError("Kubernetes lifecycle read scope MUST be non-empty")
        if len(object_uids) > _MAX_OBSERVATIONS_PER_APPEND:
            raise ValueError("Kubernetes lifecycle read exceeds its UID bound")
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("Kubernetes lifecycle read interval MUST be aware and positive")
        if not 1 <= limit <= _MAX_OBSERVATIONS_PER_APPEND + 1:
            raise ValueError("Kubernetes lifecycle read limit exceeds its bound")
        if any(not uid.strip() or len(uid) > 512 for uid in object_uids):
            raise ValueError("Kubernetes lifecycle read UIDs MUST be bounded")
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT cluster_ref, namespace, object_uid, owner_uid, reason, category, "
                "event_type, event_time, recorded_time, source_revision, record, evidence_ref "
                "FROM kubernetes_lifecycle_observation "
                "WHERE cluster_ref = %s "
                "AND object_uid = ANY(%s) "
                "AND event_time >= %s AND event_time <= %s "
                "ORDER BY event_time, evidence_ref LIMIT %s",
                (
                    cluster_ref,
                    list(object_uids),
                    start,
                    end,
                    limit,
                ),
            )
            rows = await cursor.fetchall()
        return tuple(_observation_from_row(row) for row in rows)

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
    ) -> KubernetesLifecycleReadSnapshot:
        """Read cursor health and observations under one transaction snapshot."""

        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            await self._lock_cluster(connection, cluster_ref)
            state_cursor = await connection.execute(
                "SELECT resource_version, updated_at, complete, limitation "
                "FROM kubernetes_lifecycle_cursor WHERE cluster_ref = %s",
                (cluster_ref,),
            )
            state_row = await state_cursor.fetchone()
            observation_cursor = await connection.execute(
                "SELECT cluster_ref, namespace, object_uid, owner_uid, reason, category, "
                "event_type, event_time, recorded_time, source_revision, record, evidence_ref "
                "FROM kubernetes_lifecycle_observation "
                "WHERE cluster_ref = %s "
                "AND object_uid = ANY(%s) "
                "AND event_time >= %s AND event_time <= %s "
                "ORDER BY event_time, evidence_ref LIMIT %s",
                (
                    cluster_ref,
                    list(object_uids),
                    start,
                    end,
                    limit,
                ),
            )
            rows = await observation_cursor.fetchall()
        state = (
            None
            if state_row is None
            else KubernetesLifecycleCursorState(
                resource_version=(
                    None
                    if state_row["resource_version"] is None
                    else str(state_row["resource_version"])
                ),
                updated_at=state_row["updated_at"],
                complete=bool(state_row["complete"]),
                limitation=(
                    None if state_row["limitation"] is None else str(state_row["limitation"])
                ),
            )
        )
        return KubernetesLifecycleReadSnapshot(
            state=state,
            observations=tuple(_observation_from_row(row) for row in rows),
        )

    async def append_pod_identities(
        self,
        identities: tuple[KubernetesPodLifecycleIdentity, ...],
    ) -> None:
        """Append immutable inventory-grounded Pod identities idempotently."""

        if len(identities) > 20_000:
            raise ValueError("Kubernetes Pod lifecycle identity append exceeds its bound")
        if not identities:
            return
        cluster_refs = {item.cluster_ref for item in identities}
        if len(cluster_refs) != 1:
            raise ValueError("Kubernetes Pod lifecycle identity append mixed clusters")
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cluster_ref = next(iter(cluster_refs))
            await self._lock_cluster(connection, cluster_ref)
            for identity in identities:
                inserted = await connection.execute(
                    "INSERT INTO kubernetes_pod_lifecycle_identity ("
                    "cluster_ref, namespace, pod_id, pod_uid, controller_uid, "
                    "root_controller_uid, root_controller_kind, observed_at, "
                    "source_revision, evidence_ref"
                    ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (cluster_ref, pod_uid) DO NOTHING "
                    "RETURNING pod_uid",
                    (
                        identity.cluster_ref,
                        identity.namespace,
                        identity.pod_id,
                        identity.pod_uid,
                        identity.controller_uid,
                        identity.root_controller_uid,
                        identity.root_controller_kind,
                        identity.observed_at,
                        identity.source_revision,
                        identity.evidence_ref,
                    ),
                )
                if await inserted.fetchone() is not None:
                    continue
                existing = await connection.execute(
                    "SELECT cluster_ref, namespace, pod_id, pod_uid, controller_uid, "
                    "root_controller_uid, root_controller_kind "
                    "FROM kubernetes_pod_lifecycle_identity "
                    "WHERE cluster_ref = %s AND pod_uid = %s",
                    (identity.cluster_ref, identity.pod_uid),
                )
                row = await existing.fetchone()
                if row is None or (
                    str(row["namespace"]),
                    str(row["pod_id"]),
                    str(row["controller_uid"]),
                    str(row["root_controller_uid"]),
                    str(row["root_controller_kind"]),
                ) != (
                    identity.namespace,
                    identity.pod_id,
                    identity.controller_uid,
                    identity.root_controller_uid,
                    identity.root_controller_kind,
                ):
                    raise ValueError(
                        "Kubernetes Pod lifecycle identity conflicts with retained lineage"
                    )

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
    ) -> KubernetesPodLifecycleCohortSnapshot:
        """Read exact Pod identities and their events for one retained root controller."""

        if not all(item.strip() for item in (cluster_ref, namespace, root_controller_uid)):
            raise ValueError("Kubernetes Pod lifecycle cohort identity MUST be non-empty")
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("Kubernetes Pod lifecycle cohort interval MUST be aware and positive")
        if not 1 <= identity_limit <= 33 or not 1 <= event_limit <= 257:
            raise ValueError("Kubernetes Pod lifecycle cohort bounds are invalid")
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            await self._lock_cluster(connection, cluster_ref)
            state_cursor = await connection.execute(
                "SELECT resource_version, updated_at, complete, limitation "
                "FROM kubernetes_lifecycle_cursor WHERE cluster_ref = %s",
                (cluster_ref,),
            )
            state_row = await state_cursor.fetchone()
            identity_cursor = await connection.execute(
                "SELECT cluster_ref, namespace, pod_id, pod_uid, controller_uid, "
                "root_controller_uid, root_controller_kind, observed_at, "
                "source_revision, evidence_ref "
                "FROM kubernetes_pod_lifecycle_identity "
                "WHERE cluster_ref = %s AND namespace = %s "
                "AND root_controller_uid = %s AND observed_at <= %s "
                "ORDER BY observed_at, pod_uid LIMIT %s",
                (cluster_ref, namespace, root_controller_uid, end, identity_limit),
            )
            identity_rows = await identity_cursor.fetchall()
            pod_uids = [str(row["pod_uid"]) for row in identity_rows]
            observation_rows: list[dict[str, Any]] = []
            if pod_uids:
                observation_cursor = await connection.execute(
                    "SELECT cluster_ref, namespace, object_uid, owner_uid, reason, category, "
                    "event_type, event_time, recorded_time, source_revision, record, evidence_ref "
                    "FROM kubernetes_lifecycle_observation "
                    "WHERE cluster_ref = %s AND object_uid = ANY(%s) "
                    "AND event_time >= %s AND event_time <= %s "
                    "ORDER BY event_time, evidence_ref LIMIT %s",
                    (cluster_ref, pod_uids, start, end, event_limit),
                )
                observation_rows = await observation_cursor.fetchall()
        state = _cursor_state(state_row)
        return KubernetesPodLifecycleCohortSnapshot(
            state=state,
            identities=tuple(_pod_identity_from_row(row) for row in identity_rows),
            observations=tuple(_observation_from_row(row) for row in observation_rows),
        )

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        dsn = self._config.dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        return await psycopg.AsyncConnection.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _lock_cluster(
        self, connection: psycopg.AsyncConnection[Any], cluster_ref: str
    ) -> None:
        """Serialize every cursor read/create/advance for one cluster.

        A `SELECT ... FOR UPDATE` alone cannot lock a row that does not exist yet,
        so two concurrent first-ever collections (or two collections racing right
        after a cursor-expiry gap cleared the row) could both observe an absent
        cursor and both proceed as the sole writer. This transaction-scoped
        advisory lock, keyed by `cluster_ref`, is acquired before that row lookup so
        the second caller blocks until the first commits or rolls back and then
        correctly observes the now-current cursor.
        """

        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (f"kubernetes-lifecycle-cursor:{cluster_ref}",),
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _record(observation: KubernetesLifecycleObservation) -> dict[str, object]:
    return {
        "cluster_ref": observation.cluster_ref,
        "namespace": observation.namespace,
        "object_uid": observation.object_uid,
        "owner_uid": observation.owner_uid,
        "reason": observation.reason,
        "category": observation.category,
        "event_type": observation.event_type,
        "event_time": observation.event_time.isoformat(),
        "recorded_time": observation.recorded_time.isoformat(),
        "source_revision": observation.source_revision,
        "evidence_ref": observation.evidence_ref,
    }


def _observation_from_row(row: dict[str, Any]) -> KubernetesLifecycleObservation:
    """Decode one database row using the typed columns, never arbitrary JSON payload."""

    return KubernetesLifecycleObservation(
        cluster_ref=str(row["cluster_ref"]),
        namespace=None if row["namespace"] is None else str(row["namespace"]),
        object_uid=str(row["object_uid"]),
        owner_uid=None if row["owner_uid"] is None else str(row["owner_uid"]),
        reason=str(row["reason"]),
        category=str(row["category"]),
        event_type=str(row["event_type"]),
        event_time=row["event_time"],
        recorded_time=row["recorded_time"],
        source_revision=str(row["source_revision"]),
        evidence_ref=str(row["evidence_ref"]),
    )


def _pod_identity_from_row(row: dict[str, Any]) -> KubernetesPodLifecycleIdentity:
    return KubernetesPodLifecycleIdentity(
        cluster_ref=str(row["cluster_ref"]),
        namespace=str(row["namespace"]),
        pod_id=str(row["pod_id"]),
        pod_uid=str(row["pod_uid"]),
        controller_uid=str(row["controller_uid"]),
        root_controller_uid=str(row["root_controller_uid"]),
        root_controller_kind=str(row["root_controller_kind"]),
        observed_at=row["observed_at"],
        source_revision=str(row["source_revision"]),
        evidence_ref=str(row["evidence_ref"]),
    )


def _cursor_state(row: dict[str, Any] | None) -> KubernetesLifecycleCursorState | None:
    if row is None:
        return None
    return KubernetesLifecycleCursorState(
        resource_version=None if row["resource_version"] is None else str(row["resource_version"]),
        updated_at=row["updated_at"],
        complete=bool(row["complete"]),
        limitation=None if row["limitation"] is None else str(row["limitation"]),
    )


__all__ = [
    "PostgresKubernetesLifecycleStore",
    "PostgresKubernetesLifecycleStoreConfig",
]
