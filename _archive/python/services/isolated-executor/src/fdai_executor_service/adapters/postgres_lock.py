"""PostgreSQL session advisory lock for cross-replica Executor serialization."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import psycopg

_LOGGER = logging.getLogger("fdai.isolated_executor.postgres_lock")
_LOCK_SQL = "SELECT pg_advisory_lock(hashtextextended(%s, 0))"
_UNLOCK_SQL = "SELECT pg_advisory_unlock(hashtextextended(%s, 0))"


@dataclass(frozen=True, slots=True)
class PostgresAdvisoryResourceLockConfig:
    """Bounded connection and acquisition settings for resource locks."""

    dsn: str
    lock_timeout_ms: int = 30_000
    connect_timeout_s: int = 10


class PostgresAdvisoryResourceLock:
    """Hold a crash-safe session lock for one exact logical target."""

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
        """Hold the lock on a dedicated connection for the critical section."""

        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            autocommit=True,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            if self._config.lock_timeout_ms > 0:
                await connection.execute(
                    "SELECT set_config('lock_timeout', %s, false)",
                    (str(self._config.lock_timeout_ms),),
                )
            await connection.execute(_LOCK_SQL, (resource_id,))
            try:
                yield
            finally:
                try:
                    await connection.execute(_UNLOCK_SQL, (resource_id,))
                except Exception:  # noqa: BLE001 - connection close releases session lock
                    _LOGGER.warning(
                        "advisory_unlock_failed",
                        extra={"resource_id_digest": _resource_digest(resource_id)},
                        exc_info=True,
                    )


def _resource_digest(resource_id: str) -> str:
    import hashlib

    return hashlib.sha256(resource_id.encode()).hexdigest()[:16]


__all__ = [
    "PostgresAdvisoryResourceLock",
    "PostgresAdvisoryResourceLockConfig",
]
