"""Exclusive Core-owned task-worker runtime lease and startup schema verification."""

from __future__ import annotations

import asyncio
from typing import Any

import psycopg

from fdai.delivery.persistence.postgres_task_worker import (
    PostgresTaskWorkerStore,
    PostgresTaskWorkerStoreConfig,
)

_LEASE_NAMESPACE = 805
_LEASE_KEY = 1


class PostgresTaskWorkerRuntimeStore(PostgresTaskWorkerStore):
    """Keep one runtime owner per database so startup cannot recover another live runtime.

    The long-lived advisory lease is separate from each bounded store transaction. Lease loss
    fails subsequent operations. It authorizes no resource mutation and does not reset budgets.
    """

    def __init__(self, *, config: PostgresTaskWorkerStoreConfig) -> None:
        super().__init__(config=config)
        self._lease: psycopg.AsyncConnection[dict[str, Any]] | None = None
        self._lease_lock = asyncio.Lock()

    async def open(self) -> None:
        """Require the Core role, expected tables and an exclusive lease before recovery."""
        if self._lease is not None:
            raise RuntimeError("worker runtime store is already open")
        connection = await super()._connect()
        try:
            await connection.set_autocommit(True)
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                (str(self._config.statement_timeout_ms),),
            )
            cursor = await connection.execute("SELECT current_user AS role, session_user AS login")
            row = await cursor.fetchone()
            if row is None or row["role"] != "fdai_core" or row["login"] != "fdai_core":
                raise RuntimeError("worker runtime requires the fdai_core database role")
            await connection.execute(
                "SELECT worker_id, parent_trace_ref, cancellation_owner, status, request, "
                "capabilities, usage, result, created_at, updated_at, heartbeat_at, revision "
                "FROM task_worker_run LIMIT 0"
            )
            await connection.execute(
                "SELECT worker_id, sequence, kind, at, details FROM task_worker_event LIMIT 0"
            )
            cursor = await connection.execute(
                "SELECT has_table_privilege(current_user, 'task_worker_run', 'INSERT') "
                "AND has_table_privilege(current_user, 'task_worker_run', 'UPDATE') "
                "AND has_table_privilege(current_user, 'task_worker_event', 'INSERT') AS writable"
            )
            row = await cursor.fetchone()
            if row is None or row["writable"] is not True:
                raise RuntimeError("worker runtime store grants are incomplete")
            cursor = await connection.execute(
                "SELECT pg_try_advisory_lock(%s, %s) AS acquired", (_LEASE_NAMESPACE, _LEASE_KEY)
            )
            row = await cursor.fetchone()
            if row is None or row["acquired"] is not True:
                raise RuntimeError("another Core runtime owns the task-worker lease")
        except BaseException:
            await connection.close()
            raise
        self._lease = connection

    async def assert_lease(self) -> None:
        """Verify the existing session's lease; never silently reacquire or recover it."""
        async with self._lease_lock:
            if self._lease is None or self._lease.closed:
                raise RuntimeError("task-worker runtime lease is unavailable")
            cursor = await self._lease.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' "
                "AND pid=pg_backend_pid() AND classid=%s AND objid=%s "
                "AND objsubid=2 AND granted) AS held",
                (_LEASE_NAMESPACE, _LEASE_KEY),
            )
            row = await cursor.fetchone()
            if row is None or row["held"] is not True:
                raise RuntimeError("task-worker runtime lease was lost")

    async def verify_inventory_source(self) -> None:
        """Check required recorded-source tables without reading inventory or contacting Azure."""
        async with await self._connect() as connection:
            await connection.set_read_only(True)
            await self._timeout(connection)
            await connection.execute("SELECT singleton, snapshot_id FROM inventory_active LIMIT 0")
            await connection.execute(
                "SELECT id, status, observation_kind, started_at, completed_at "
                "FROM inventory_snapshot LIMIT 0"
            )
            await connection.execute(
                "SELECT snapshot_id, resource_id, resource_type, props "
                "FROM inventory_snapshot_resource LIMIT 0"
            )
            await connection.execute("SELECT resource_id FROM inventory_realtime_resource LIMIT 0")

    async def aclose(self) -> None:
        """Release this store's session; callers retain any drain or recovery failure."""
        async with self._lease_lock:
            connection, self._lease = self._lease, None
            if connection is not None:
                await connection.close()

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        await self.assert_lease()
        return await super()._connect()
