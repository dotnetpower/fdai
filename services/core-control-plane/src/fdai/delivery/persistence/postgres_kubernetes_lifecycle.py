"""PostgreSQL persistence for append-only Kubernetes lifecycle observations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from fdai.core.ontology_platform.kubernetes_lifecycle import (
    KubernetesLifecycleBatch,
    KubernetesLifecycleCursor,
    KubernetesLifecycleObservation,
)


@dataclass(frozen=True, slots=True)
class PostgresKubernetesLifecycleConfig:
    """Database and statement bounds for lifecycle persistence."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("Kubernetes lifecycle DSN MUST be non-empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("Kubernetes lifecycle database timeouts MUST be positive")


class PostgresKubernetesLifecycleStore:
    """Lease, append, and query lifecycle evidence without ontology writes."""

    def __init__(self, *, config: PostgresKubernetesLifecycleConfig) -> None:
        self._config = config

    async def acquire(
        self,
        *,
        cluster_ref: str,
        holder: str,
        now: datetime,
        lease_until: datetime,
    ) -> KubernetesLifecycleCursor | None:
        """Acquire one cluster collector lease or return no work."""

        if not cluster_ref or not holder:
            raise ValueError("Kubernetes lifecycle lease identity MUST be non-empty")
        if now.tzinfo is None or lease_until.tzinfo is None or lease_until <= now:
            raise ValueError("Kubernetes lifecycle lease times are invalid")
        async with await self._connect() as conn:
            async with conn.transaction():
                await self._timeout(conn)
                cursor = await conn.execute(
                    """
                    INSERT INTO kubernetes_lifecycle_cursor (
                        cluster_ref, sequence, resume_token, coverage_started_at,
                        coverage_through_at, retention_floor_at, limitation,
                        lease_holder, lease_expires_at
                    )
                    VALUES (%s, 0, NULL, %s, %s, %s, 'initializing', %s, %s)
                    ON CONFLICT (cluster_ref) DO UPDATE
                       SET lease_holder = EXCLUDED.lease_holder,
                           lease_expires_at = EXCLUDED.lease_expires_at
                     WHERE kubernetes_lifecycle_cursor.lease_holder IS NULL
                        OR kubernetes_lifecycle_cursor.lease_holder = EXCLUDED.lease_holder
                        OR kubernetes_lifecycle_cursor.lease_expires_at <= %s
                    RETURNING cluster_ref, sequence, resume_token, coverage_started_at,
                              coverage_through_at, retention_floor_at, limitation
                    """,
                    (cluster_ref, now, now, now, holder, lease_until, now),
                )
                row = await cursor.fetchone()
        return _cursor(row) if row is not None else None

    async def append(
        self,
        batch: KubernetesLifecycleBatch,
        *,
        holder: str,
        now: datetime,
    ) -> bool:
        """Atomically append observations and advance one locally monotonic cursor."""

        async with await self._connect() as conn:
            async with conn.transaction():
                await self._timeout(conn)
                locked = await conn.execute(
                    """
                    SELECT sequence, coverage_started_at, coverage_through_at
                      FROM kubernetes_lifecycle_cursor
                     WHERE cluster_ref = %s
                       AND lease_holder = %s
                       AND lease_expires_at > %s
                     FOR UPDATE
                    """,
                    (batch.cluster_ref, holder, now),
                )
                row = await locked.fetchone()
                if row is None or row["sequence"] != batch.expected_sequence:
                    return False
                if batch.coverage_through_at < row["coverage_through_at"]:
                    return False
                if batch.observations:
                    sql_cursor = conn.cursor()
                    await sql_cursor.executemany(
                        """
                        INSERT INTO kubernetes_lifecycle_observation (
                            observation_id, cluster_ref, event_uid, object_uid, object_kind,
                            namespace, owner_uid, reason, event_type, lifecycle_kind, action,
                            occurred_at, recorded_at, source_revision, occurrence_count,
                            evidence_ref
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (observation_id) DO NOTHING
                        """,
                        tuple(_observation_values(item) for item in batch.observations),
                    )
                updated = await conn.execute(
                    """
                    UPDATE kubernetes_lifecycle_cursor
                       SET sequence = sequence + 1,
                           resume_token = %s,
                           coverage_started_at = GREATEST(coverage_started_at, %s),
                           coverage_through_at = %s,
                           retention_floor_at = GREATEST(retention_floor_at, %s),
                           limitation = %s,
                           lease_holder = NULL,
                           lease_expires_at = NULL,
                           updated_at = %s
                     WHERE cluster_ref = %s
                       AND sequence = %s
                       AND lease_holder = %s
                    """,
                    (
                        batch.next_resume_token,
                        batch.coverage_started_at,
                        batch.coverage_through_at,
                        batch.coverage_started_at,
                        batch.limitation,
                        now,
                        batch.cluster_ref,
                        batch.expected_sequence,
                        holder,
                    ),
                )
                return updated.rowcount == 1

    async def read_cursor(self, cluster_ref: str) -> KubernetesLifecycleCursor | None:
        """Return one durable cursor without lease material."""

        async with await self._connect() as conn:
            await self._timeout(conn)
            cursor = await conn.execute(
                """
                SELECT cluster_ref, sequence, resume_token, coverage_started_at,
                       coverage_through_at, retention_floor_at, limitation
                  FROM kubernetes_lifecycle_cursor
                 WHERE cluster_ref = %s
                """,
                (cluster_ref,),
            )
            row = await cursor.fetchone()
        return _cursor(row) if row is not None else None

    async def read_observations(
        self,
        *,
        cluster_ref: str,
        object_uid: str | None,
        since: datetime,
        limit: int = 257,
    ) -> tuple[KubernetesLifecycleObservation, ...]:
        """Read newest bounded evidence through indexed cluster or object scope."""

        if not 1 <= limit <= 1000:
            raise ValueError("Kubernetes lifecycle read limit MUST be in [1, 1000]")
        predicate = "cluster_ref = %s AND occurred_at >= %s"
        params: list[object] = [cluster_ref, since]
        if object_uid is not None:
            predicate += " AND object_uid = %s"
            params.append(object_uid)
        params.append(limit)
        async with await self._connect() as conn:
            await self._timeout(conn)
            cursor = await conn.execute(
                f"""
                SELECT observation_id, cluster_ref, event_uid, object_uid, object_kind,
                       namespace, owner_uid, reason, event_type, lifecycle_kind, action,
                       occurred_at, recorded_at, source_revision, occurrence_count,
                       evidence_ref
                  FROM kubernetes_lifecycle_observation
                 WHERE {predicate}
                 ORDER BY occurred_at DESC, evidence_ref DESC
                 LIMIT %s
                """,  # noqa: S608 - predicate is selected only from fixed literals
                tuple(params),
            )
            rows: Sequence[dict[str, Any]] = await cursor.fetchall()
        return tuple(_observation(row) for row in rows)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        dsn = _psycopg_dsn(self._config.dsn)
        return await psycopg.AsyncConnection.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, conn: psycopg.AsyncConnection[Any]) -> None:
        await conn.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _psycopg_dsn(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _cursor(row: dict[str, Any]) -> KubernetesLifecycleCursor:
    return KubernetesLifecycleCursor(
        cluster_ref=str(row["cluster_ref"]),
        sequence=cast(int, row["sequence"]),
        resume_token=str(row["resume_token"]) if row["resume_token"] is not None else None,
        coverage_started_at=cast(datetime, row["coverage_started_at"]),
        coverage_through_at=cast(datetime, row["coverage_through_at"]),
        retention_floor_at=cast(datetime, row["retention_floor_at"]),
        limitation=str(row["limitation"]) if row["limitation"] is not None else None,
    )


def _observation_values(item: KubernetesLifecycleObservation) -> tuple[object, ...]:
    return (
        item.observation_id,
        item.cluster_ref,
        item.event_uid,
        item.object_uid,
        item.object_kind,
        item.namespace,
        item.owner_uid,
        item.reason,
        item.event_type,
        item.lifecycle_kind,
        item.action,
        item.occurred_at,
        item.recorded_at,
        item.source_revision,
        item.occurrence_count,
        item.evidence_ref,
    )


def _observation(row: dict[str, Any]) -> KubernetesLifecycleObservation:
    return KubernetesLifecycleObservation(
        observation_id=str(row["observation_id"]),
        cluster_ref=str(row["cluster_ref"]),
        event_uid=str(row["event_uid"]),
        object_uid=str(row["object_uid"]),
        object_kind=str(row["object_kind"]),
        namespace=str(row["namespace"]) if row["namespace"] is not None else None,
        owner_uid=str(row["owner_uid"]) if row["owner_uid"] is not None else None,
        reason=str(row["reason"]),
        event_type=str(row["event_type"]),
        lifecycle_kind=str(row["lifecycle_kind"]),
        action=str(row["action"]),
        occurred_at=cast(datetime, row["occurred_at"]),
        recorded_at=cast(datetime, row["recorded_at"]),
        source_revision=str(row["source_revision"]),
        occurrence_count=cast(int, row["occurrence_count"]),
        evidence_ref=str(row["evidence_ref"]),
    )


__all__ = [
    "PostgresKubernetesLifecycleConfig",
    "PostgresKubernetesLifecycleStore",
]
