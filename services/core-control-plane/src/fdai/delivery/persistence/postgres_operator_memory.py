"""PostgresOperatorMemoryStore - persistent :class:`OperatorMemoryStore`.

Realizes :class:`~fdai.core.operator_memory.store.OperatorMemoryStore`
against the ``operator_memory`` table created by the alembic migration
``20260706_0006_operator_memory``. Kept in the same ``delivery/persistence``
folder as :class:`PostgresStateStore` so the two adapters share the
psycopg 3 dependency and follow the same DSN + statement-timeout
contract.

Design invariants (mirror the in-memory store)
----------------------------------------------
- Append-only. :meth:`append` INSERTs one row; a duplicate ``id`` is
  refused via the PRIMARY KEY, surfaced to the caller as
  :class:`OperatorMemoryPolicyError(code="duplicate_id")` so the two
  backends are indistinguishable to the composer.
- Policy validation runs first, in Python, via the shared
  ``_reject_policy_violations`` helper - the SQL CHECKs are defense
  in depth, not the primary gate, so the caller sees structured
  ``OperatorMemoryPolicyError`` codes rather than opaque SQL errors.
- :meth:`list_active_for_scope` filters superseded rows AND expired
  rows in the same query so a composer never has to post-filter.
  Expiry math uses ``NOW() - created_at < ttl_seconds * interval '1 sec'``
  which matches the ``_is_expired`` helper's semantics
  (``ttl_seconds`` NULL means indefinite).
- :meth:`supersede` re-reads the target row inside the same
  transaction so a concurrent supersede raises ``already_superseded``
  rather than silently overwriting the pointer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from fdai.core.operator_memory.store import (
    OperatorMemoryPolicyError,
    OperatorMemoryStore,
    _reject_policy_violations,
)
from fdai.core.operator_memory.types import (
    MemoryCategory,
    MemorySource,
    OperatorMemoryEntry,
    ScopeKind,
)


@dataclass(frozen=True, slots=True)
class PostgresOperatorMemoryStoreConfig:
    """DSN + optional per-statement timeout for the adapter."""

    dsn: str
    """psycopg 3 connection string. e.g.
    ``postgresql://user:password@host:5432/db?sslmode=require``."""

    statement_timeout_ms: int = 15_000
    """Applied via ``SET LOCAL`` on every operation; fails fast rather than
    blocking the event loop on a stuck query."""

    connect_timeout_s: int = 10
    """Bound the TCP + auth handshake so a dead DB fails fast instead of
    hanging the event loop for ~2 minutes on the kernel TCP retry budget
    (``statement_timeout`` only starts *after* connect succeeds)."""


class PostgresOperatorMemoryStore(OperatorMemoryStore):
    """Async :class:`OperatorMemoryStore` implementation for PostgreSQL."""

    def __init__(self, *, config: PostgresOperatorMemoryStoreConfig) -> None:
        if not config.dsn:
            raise ValueError("PostgresOperatorMemoryStoreConfig.dsn MUST NOT be empty")
        if config.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if config.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        self._config: Final[PostgresOperatorMemoryStoreConfig] = config

    # ------------------------------------------------------------------
    # OperatorMemoryStore
    # ------------------------------------------------------------------

    async def append(self, entry: OperatorMemoryEntry) -> OperatorMemoryEntry:
        _reject_policy_violations(entry)
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                try:
                    await conn.execute(
                        """
                        INSERT INTO operator_memory
                            (id, scope_kind, scope_ref, category, body,
                             source_event, source_ref, author, approved_by,
                             created_at, superseded_by, ttl_seconds)
                        VALUES
                            (%s::uuid, %s, %s, %s, %s,
                             %s, %s, %s, %s,
                             %s, %s, %s)
                        """,
                        (
                            str(entry.id),
                            entry.scope_kind.value,
                            entry.scope_ref,
                            entry.category.value,
                            entry.body,
                            entry.source_event.value,
                            entry.source_ref,
                            entry.author,
                            entry.approved_by,
                            entry.created_at,
                            str(entry.superseded_by) if entry.superseded_by else None,
                            entry.ttl_seconds,
                        ),
                    )
                except psycopg.errors.UniqueViolation as exc:
                    # Only the PRIMARY KEY on ``id`` produces UniqueViolation
                    # here; the CHECK constraints raise CheckViolation.
                    raise OperatorMemoryPolicyError(
                        "duplicate_id",
                        f"entry {entry.id} already exists in the store",
                    ) from exc
        return entry

    async def list_active_for_scope(
        self, *, scope_kind: ScopeKind, scope_ref: str
    ) -> tuple[OperatorMemoryEntry, ...]:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cur = await conn.execute(
                    """
                    SELECT id, scope_kind, scope_ref, category, body,
                           source_event, source_ref, author, approved_by,
                           created_at, superseded_by, ttl_seconds
                      FROM operator_memory
                     WHERE scope_kind = %s
                       AND scope_ref = %s
                       AND superseded_by IS NULL
                       AND (
                            ttl_seconds IS NULL
                         OR NOW() - created_at < make_interval(secs => ttl_seconds)
                       )
                     ORDER BY created_at ASC, id ASC
                    """,
                    (scope_kind.value, scope_ref),
                )
                rows = await cur.fetchall()
        return tuple(_row_to_entry(row) for row in rows)

    async def supersede(self, *, entry_id: UUID, superseded_by: UUID) -> None:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cur = await conn.execute(
                    "SELECT superseded_by FROM operator_memory WHERE id = %s::uuid FOR UPDATE",
                    (str(entry_id),),
                )
                row = await cur.fetchone()
                if row is None:
                    raise LookupError(f"operator memory entry {entry_id} not found")
                if row[0] is not None:
                    raise OperatorMemoryPolicyError(
                        "already_superseded",
                        f"entry {entry_id} is already superseded by {row[0]}",
                    )
                await conn.execute(
                    "UPDATE operator_memory SET superseded_by = %s::uuid WHERE id = %s::uuid",
                    (str(superseded_by), str(entry_id)),
                )

    async def list_for_review(
        self,
        *,
        limit: int,
        scope_kind: ScopeKind | None = None,
        scope_ref: str | None = None,
    ) -> tuple[OperatorMemoryEntry, ...]:
        if not 1 <= limit <= 200:
            raise ValueError("operator memory review limit MUST be in [1, 200]")
        clauses: list[str] = []
        params: list[object] = []
        if scope_kind is not None:
            clauses.append("scope_kind = %s")
            params.append(scope_kind.value)
        if scope_ref is not None:
            clauses.append("scope_ref = %s")
            params.append(scope_ref)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cursor = await conn.execute(
                    f"""
                    SELECT id, scope_kind, scope_ref, category, body,
                           source_event, source_ref, author, approved_by,
                           created_at, superseded_by, ttl_seconds
                      FROM operator_memory
                      {where}
                     ORDER BY created_at DESC, id DESC
                     LIMIT %s
                    """,  # noqa: S608 - where uses fixed clauses only
                    tuple(params),
                )
                rows = await cursor.fetchall()
        return tuple(_row_to_entry(row) for row in rows)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _set_statement_timeout(self, conn: psycopg.AsyncConnection[Any]) -> None:
        # SET LOCAL does not accept parametrized values in Postgres;
        # inline the (validated int) timeout literally.
        ms = int(self._config.statement_timeout_ms)
        await conn.execute(f"SET LOCAL statement_timeout = {ms}")


def _row_to_entry(row: dict[str, Any]) -> OperatorMemoryEntry:
    """Coerce one ``dict_row`` result into an :class:`OperatorMemoryEntry`.

    ``psycopg`` returns UUID + datetime columns as native Python
    ``uuid.UUID`` / ``datetime.datetime`` objects, but the CHECK
    constraints do not preserve stored-vs-parsed distinctions - we
    still coerce defensively so a row round-tripped through a JSON
    export/import path lands on the right types.
    """

    created_at = row["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    superseded_by_raw = row["superseded_by"]
    superseded_by = _coerce_uuid_optional(superseded_by_raw)
    return OperatorMemoryEntry(
        id=_coerce_uuid(row["id"]),
        scope_kind=ScopeKind(row["scope_kind"]),
        scope_ref=row["scope_ref"],
        category=MemoryCategory(row["category"]),
        body=row["body"],
        source_event=MemorySource(row["source_event"]),
        source_ref=row["source_ref"],
        author=row["author"],
        approved_by=row["approved_by"],
        created_at=created_at,
        superseded_by=superseded_by,
        ttl_seconds=row["ttl_seconds"],
    )


def _coerce_uuid(value: Any) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _coerce_uuid_optional(value: Any) -> UUID | None:
    if value is None:
        return None
    return _coerce_uuid(value)


__all__ = [
    "PostgresOperatorMemoryStore",
    "PostgresOperatorMemoryStoreConfig",
]
