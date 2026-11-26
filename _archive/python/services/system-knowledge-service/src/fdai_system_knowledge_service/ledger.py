"""Durable single-replica SQLite claims for Teams knowledge replies."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


class DeliveryLedger(Protocol):
    """Persist delivery ownership across retries and process restarts."""

    def start(self) -> Awaitable[None]: ...

    def claim(self, key: str) -> Awaitable[bool]: ...

    def mark_sending(self, key: str, response_digest: str) -> Awaitable[None]: ...

    def mark_delivered(self, key: str, provider_activity_id: str) -> Awaitable[None]: ...

    def mark_ambiguous(self, key: str) -> Awaitable[None]: ...

    def release_retryable(self, key: str) -> Awaitable[None]: ...

    def state(self, key: str) -> Awaitable[str | None]: ...

    def aclose(self) -> Awaitable[None]: ...


class MessageLedger:
    """Persist send ownership so restart ambiguity never causes an automatic repost."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Create the service-owned schema and reconcile interrupted states."""

        self._path.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            await asyncio.to_thread(self._initialize)
            await asyncio.to_thread(self._reconcile)

    async def claim(self, key: str) -> bool:
        """Claim a new provider message exactly once within the durable store."""

        async with self._lock:
            return await asyncio.to_thread(self._claim, key)

    async def mark_sending(self, key: str, response_digest: str) -> None:
        """Fence provider I/O after the complete response has been derived."""

        async with self._lock:
            await asyncio.to_thread(self._transition, key, "processing", "sending", response_digest)

    async def mark_delivered(self, key: str, provider_activity_id: str) -> None:
        """Close one send after a valid provider acknowledgement."""

        async with self._lock:
            await asyncio.to_thread(
                self._transition,
                key,
                "sending",
                "delivered",
                None,
                provider_activity_id,
            )

    async def mark_ambiguous(self, key: str) -> None:
        """Close an interrupted send without retrying duplicate risk."""

        async with self._lock:
            await asyncio.to_thread(self._transition, key, "sending", "ambiguous", None)

    async def release_retryable(self, key: str) -> None:
        """Release a claim only when the provider definitively sent nothing."""

        async with self._lock:
            await asyncio.to_thread(self._release, key)

    async def state(self, key: str) -> str | None:
        """Return one content-free delivery state for tests and diagnostics."""

        async with self._lock:
            return await asyncio.to_thread(self._state, key)

    async def aclose(self) -> None:
        """Close the local ledger; connections are operation-scoped."""

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_message_delivery (
                    message_key TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    response_digest TEXT,
                    provider_activity_id TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _reconcile(self) -> None:
        now = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM knowledge_message_delivery WHERE state = 'processing'")
            connection.execute(
                """
                UPDATE knowledge_message_delivery
                SET state = 'ambiguous', updated_at = ?
                WHERE state = 'sending'
                """,
                (now,),
            )

    def _claim(self, key: str) -> bool:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO knowledge_message_delivery
                    (message_key, state, updated_at)
                VALUES (?, 'processing', ?)
                """,
                (key, datetime.now(UTC).isoformat()),
            )
            return cursor.rowcount == 1

    def _transition(
        self,
        key: str,
        expected: str,
        target: str,
        response_digest: str | None,
        provider_activity_id: str | None = None,
    ) -> None:
        assignments = ["state = ?", "updated_at = ?"]
        values: list[str | None] = [target, datetime.now(UTC).isoformat()]
        if response_digest is not None:
            assignments.append("response_digest = ?")
            values.append(response_digest)
        if provider_activity_id is not None:
            assignments.append("provider_activity_id = ?")
            values.append(provider_activity_id)
        values.extend((key, expected))
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                f"""
                UPDATE knowledge_message_delivery
                SET {", ".join(assignments)}
                WHERE message_key = ? AND state = ?
                """,  # noqa: S608 - assignments are fixed internal column names
                values,
            )
            if cursor.rowcount != 1:
                raise RuntimeError("system knowledge delivery transition lost ownership")

    def _release(self, key: str) -> None:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                DELETE FROM knowledge_message_delivery
                WHERE message_key = ? AND state IN ('processing', 'sending')
                """,
                (key,),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("system knowledge retry release lost ownership")

    def _state(self, key: str) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT state FROM knowledge_message_delivery WHERE message_key = ?",
                (key,),
            ).fetchone()
        return str(row[0]) if row is not None else None


__all__ = ["DeliveryLedger", "MessageLedger"]
