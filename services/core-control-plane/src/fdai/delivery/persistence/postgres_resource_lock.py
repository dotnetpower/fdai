"""PostgresAdvisoryResourceLock - distributed per-resource lock.

Realizes the :class:`~fdai.shared.providers.resource_lock.ResourceLock`
Protocol on PostgreSQL session advisory locks, so per-resource mutual
exclusion holds across every replica (not just within one process like
the in-memory :class:`~fdai.core.executor.lock.ResourceLockManager`).

Design
------
- ``hashtextextended(resource_id, 0)`` maps a resource id to a stable
  bigint key - the same id yields the same key in every replica, so
  ``pg_advisory_lock`` gives cross-replica mutual exclusion.
- The lock is *session-scoped* and held on a dedicated ``autocommit``
  connection for the whole critical section. Session locks (unlike
  ``pg_advisory_xact_lock``) do not pin an open transaction, so the
  action can run for its full duration without an idle-in-transaction
  connection.
- Crash-safety: closing the connection (normal exit OR a crashed holder)
  releases the session lock automatically, so a dead holder never wedges
  the resource.
- ``lock_timeout_ms`` bounds the acquire wait; on timeout ``acquire``
  raises (fail toward safety - the caller does not mutate) rather than
  blocking a replica forever behind a stuck holder.

psycopg 3 is already a repo dependency (see the sibling adapters).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import psycopg

_LOG = logging.getLogger(__name__)

_LOCK_SQL = "SELECT pg_advisory_lock(hashtextextended(%s, 0))"
_UNLOCK_SQL = "SELECT pg_advisory_unlock(hashtextextended(%s, 0))"


@dataclass(frozen=True, slots=True)
class PostgresAdvisoryResourceLockConfig:
    """DSN + acquire-wait bound for the distributed lock."""

    dsn: str
    """psycopg 3 connection string, e.g.
    ``postgresql://user:password@host:5432/db?sslmode=require``."""

    lock_timeout_ms: int = 30_000
    """Max wait to acquire before failing closed. ``0`` waits forever
    (matching the in-process ``asyncio.Lock`` semantics)."""

    connect_timeout_s: int = 10
    """Bound the TCP/auth handshake so a dead DB fails fast instead of
    hanging the event loop before the lock wait even begins."""


class PostgresAdvisoryResourceLock:
    """Distributed :class:`ResourceLock` via Postgres session advisory locks."""

    def __init__(self, *, config: PostgresAdvisoryResourceLockConfig) -> None:
        if not config.dsn:
            raise ValueError("PostgresAdvisoryResourceLockConfig.dsn MUST NOT be empty")
        if config.lock_timeout_ms < 0:
            raise ValueError("lock_timeout_ms MUST be >= 0")
        if config.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        self._config = config

    @asynccontextmanager
    async def acquire(self, resource_id: str) -> AsyncIterator[None]:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            autocommit=True,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            if self._config.lock_timeout_ms > 0:
                # set_config takes bind params (plain SET does not); bound
                # to the session so the advisory-lock wait is capped.
                await conn.execute(
                    "SELECT set_config('lock_timeout', %s, false)",
                    (str(self._config.lock_timeout_ms),),
                )
            await conn.execute(_LOCK_SQL, (resource_id,))
            try:
                yield
            finally:
                # Explicit unlock keeps the key count tidy; the connection
                # close below also releases every session lock, so a
                # failure here is not fatal.
                try:
                    await conn.execute(_UNLOCK_SQL, (resource_id,))
                except Exception:  # noqa: BLE001 - close() still releases it
                    _LOG.warning(
                        "advisory_unlock_failed",
                        extra={"resource_id": resource_id},
                        exc_info=True,
                    )


__all__ = [
    "PostgresAdvisoryResourceLock",
    "PostgresAdvisoryResourceLockConfig",
]
