"""Postgres-backed :class:`ConsoleReadModel` for production read-API.

The upstream repo ships :class:`InMemoryConsoleReadModel` for tests + dev.
This module supplies the counterpart used in a real deployment: a
read-only projection on top of the same schema
:class:`~fdai.delivery.persistence.postgres.PostgresStateStore` writes
to (``audit_log`` + ``state_kv``). It never mutates state and never
creates its own schema - all migrations are owned by ``alembic/versions``.

Design notes
------------

- **Same driver as the writer.** Uses ``psycopg`` 3 (already in
  ``pyproject.toml``) so no new lockfile entry lands. A connection is
  opened per operation, matching
  :class:`~fdai.delivery.persistence.postgres.PostgresStateStore` -
  scale-to-zero deployments do not benefit from a persistent pool, and
  the read-API's three routes are low-frequency compared with the
  writer path.

- **HIL queue derived from ``state_kv``, not audit.** The HIL
  park record (``hil_park:<approval_id>``) is the source of truth
  the :mod:`fdai.core.hil_resume.coordinator` writes and mutates.
  ``value->>'status' = 'pending'`` is exactly the set of pending
  approvals. The audit log records lifecycle events (requested /
  approved / rejected / timeout) but is not a queue.

- **Row → dataclass mapping is pure.** :func:`row_to_audit_item`,
  :func:`row_to_hil_queue_item`, and the KPI aggregation helpers stay
  module-level so the pytest suite exercises them without a live DB.

- **Cursor pagination is opaque.** Callers pass whatever the previous
  page returned. The current implementation encodes the last row's
  ``seq``; a future revision may switch to a compound cursor without
  breaking the callers who treat the string as an opaque token.

- **Statement timeout applies to every query.** ``SET LOCAL
  statement_timeout`` mirrors the writer's guard so a runaway audit
  aggregation cannot lock a connection indefinitely.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.read_api.persistence.postgres_projection import (
    aggregate_kpi,
    row_to_audit_item,
    row_to_hil_queue_item,
)
from fdai.delivery.read_api.persistence.postgres_projection import (
    parse_cursor as _parse_cursor,
)
from fdai.delivery.read_api.persistence.postgres_sql import (
    INCIDENT_PAGE_SQL as _INCIDENT_PAGE_SQL,
)
from fdai.delivery.read_api.persistence.postgres_sql import (
    INCIDENT_SUMMARY_HISTORY_LIMIT,
)
from fdai.delivery.read_api.read_model import (
    KPI_AUDIT_SAMPLE_LIMIT,
    AuditItem,
    AuditPage,
    AuditQueryFilters,
    ConsoleReadModel,
    DashboardKpi,
    HilQueueItem,
    HilQueuePage,
    IncidentCursor,
    IncidentPage,
    IncidentStatusFilter,
    clamp_limit,
    decode_incident_cursor,
    encode_incident_cursor,
)

DEFAULT_PENDING_STATUS: Final[str] = "pending"
PARK_KEY_PREFIX: Final[str] = "hil_park:"


@dataclass(frozen=True, slots=True)
class PostgresConsoleReadModelConfig:
    """DSN + timeouts for the read-model adapter.

    Mirrors :class:`~fdai.delivery.persistence.postgres.PostgresStateStoreConfig`
    - same DSN, independent timeouts because a KPI aggregation may run
    a bit longer than an ``INSERT``.
    """

    dsn: str
    """psycopg 3 connection string. e.g.
    ``postgresql://user:password@host:5432/db?sslmode=require``."""

    statement_timeout_ms: int = 20_000
    """Applied via ``SET LOCAL`` on every query."""

    connect_timeout_s: int = 10
    """Bound TCP + auth handshake so a dead DB fails fast."""


class PostgresConsoleReadModel(ConsoleReadModel):
    """Postgres-backed :class:`ConsoleReadModel`."""

    def __init__(self, *, config: PostgresConsoleReadModelConfig) -> None:
        if not config.dsn:
            raise ValueError("PostgresConsoleReadModelConfig.dsn MUST NOT be empty")
        if config.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if config.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        self._config = config

    # ------------------------------------------------------------------
    # ConsoleReadModel
    # ------------------------------------------------------------------

    async def list_audit(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
        correlation_id: str | None = None,
        filters: AuditQueryFilters | None = None,
    ) -> AuditPage:
        bounded = clamp_limit(limit)
        cutoff = _parse_cursor(cursor)
        # Fetch one extra row to know whether a next cursor exists without
        # a second round trip.
        fetch = bounded + 1
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                active = filters or AuditQueryFilters()
                cur = await conn.execute(
                    """
                    WITH unambiguous_events AS (
                        SELECT event_id FROM audit_log GROUP BY event_id
                        HAVING COUNT(DISTINCT correlation_id)
                            FILTER (WHERE correlation_id IS NOT NULL) = 1
                           AND MIN(correlation_id)
                            FILTER (WHERE correlation_id IS NOT NULL) = %(correlation_id)s::text
                    )
                    SELECT seq, event_id, correlation_id, actor, action_kind,
                           mode, entry, previous_hash, entry_hash, created_at
                      FROM audit_log
                     WHERE (%(cutoff)s::bigint IS NULL OR seq < %(cutoff)s::bigint)
                                               AND (%(from_seq)s::bigint IS NULL
                                                   OR seq >= %(from_seq)s::bigint)
                                               AND (%(through_seq)s::bigint IS NULL
                                                   OR seq <= %(through_seq)s::bigint)
                       AND (%(correlation_id)s::text IS NULL
                           OR correlation_id = %(correlation_id)s::text
                            OR event_id IN (SELECT event_id FROM unambiguous_events))
                       AND (%(mode)s::text IS NULL OR mode = %(mode)s::text)
                       AND (%(tier)s::text IS NULL OR LOWER(entry->>'tier') = %(tier)s::text)
                       AND (%(action_kind)s::text IS NULL
                           OR action_kind = %(action_kind)s::text)
                       AND (%(outcome)s::text IS NULL
                           OR entry->>'outcome' = %(outcome)s::text)
                       AND (%(vertical)s::text IS NULL OR REPLACE(LOWER(COALESCE(
                            entry->>'vertical', entry->>'category', ''
                       )), '_', '-') = %(vertical)s::text)
                       AND (%(window_days)s::integer IS NULL OR created_at >=
                           CURRENT_TIMESTAMP - make_interval(
                              days => %(window_days)s::integer
                           ))
                     ORDER BY seq DESC
                     LIMIT %(fetch)s
                    """,
                    {
                        "cutoff": cutoff,
                        "from_seq": active.from_seq,
                        "through_seq": active.through_seq,
                        "correlation_id": correlation_id,
                        "mode": active.mode,
                        "tier": active.tier,
                        "action_kind": active.action_kind,
                        "outcome": active.outcome,
                        "vertical": (
                            active.vertical.replace("_", "-").lower()
                            if active.vertical is not None
                            else None
                        ),
                        "window_days": active.window_days,
                        "fetch": fetch,
                    },
                )
                rows = await cur.fetchall()
        items = [row_to_audit_item(row) for row in rows[:bounded]]
        next_cursor = str(items[-1].seq) if len(rows) > bounded and items else None
        return AuditPage(items=tuple(items), next_cursor=next_cursor)

    async def list_incidents(
        self,
        *,
        status: IncidentStatusFilter = "active",
        limit: int = 50,
        cursor: str | None = None,
        vertical: str | None = None,
        correlation_id: str | None = None,
    ) -> IncidentPage:
        """Return a bounded incident roster derived from the audit ledger."""

        from fdai.delivery.read_api.routes.incident_projection import project_incidents

        if status not in {"active", "resolved", "all"}:
            raise ValueError(f"invalid incident status filter: {status!r}")
        bounded = clamp_limit(limit)
        decoded = decode_incident_cursor(cursor, status=status, vertical=vertical)
        fetch = bounded + 1
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cur = await conn.execute(
                    _INCIDENT_PAGE_SQL,
                    {
                        "snapshot_seq": decoded.snapshot_seq if decoded else None,
                        "before_seq": decoded.before_seq if decoded else None,
                        "status": status,
                        "vertical": vertical,
                        "correlation_id": correlation_id,
                        "fetch": fetch,
                        "summary_history_limit": INCIDENT_SUMMARY_HISTORY_LIMIT,
                    },
                )
                rows = await cur.fetchall()

        group_order: list[str] = []
        grouped_rows: dict[str, list[AuditItem]] = {}
        group_last_seq: dict[str, int] = {}
        group_history_count: dict[str, int] = {}
        snapshot_seq = decoded.snapshot_seq if decoded else 0
        for row in rows:
            snapshot_seq = int(row["snapshot_seq"])
            correlation = str(row["normalized_correlation_id"])
            if correlation not in grouped_rows:
                group_order.append(correlation)
                grouped_rows[correlation] = []
                group_last_seq[correlation] = int(row["group_last_seq"])
                group_history_count[correlation] = int(row["group_history_count"])
            normalized_row = dict(row)
            normalized_row["correlation_id"] = correlation
            entry = normalized_row.get("entry")
            if isinstance(entry, Mapping):
                projection_entry = dict(entry)
                severity = normalized_row.get("projection_severity")
                category = normalized_row.get("projection_category")
                if isinstance(severity, str) and severity and "severity" not in projection_entry:
                    projection_entry["severity"] = severity
                if isinstance(category, str) and category and "category" not in projection_entry:
                    projection_entry["category"] = category
                normalized_row["entry"] = projection_entry
            grouped_rows[correlation].append(row_to_audit_item(normalized_row))

        visible_correlations = group_order[:bounded]
        summaries_by_id = {
            item.correlation_id: item
            for item in project_incidents(
                (
                    audit_item
                    for correlation in visible_correlations
                    for audit_item in grouped_rows[correlation]
                ),
                status="all",
            )
        }
        items = tuple(
            replace(
                summaries_by_id[correlation],
                history_count=group_history_count[correlation],
            )
            for correlation in visible_correlations
            if correlation in summaries_by_id
        )
        next_cursor = (
            encode_incident_cursor(
                IncidentCursor(
                    snapshot_seq=snapshot_seq,
                    before_seq=group_last_seq[visible_correlations[-1]],
                    status=status,
                    vertical=vertical,
                )
            )
            if len(group_order) > bounded and visible_correlations
            else None
        )
        return IncidentPage(items=items, next_cursor=next_cursor)

    async def dashboard_metrics(self) -> DashboardKpi:
        # KPI aggregation is bounded to the newest immutable audit sample.
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cur = await conn.execute(
                    """
                                        SELECT seq, action_kind, mode, entry, created_at
                      FROM audit_log
                     ORDER BY seq DESC
                     LIMIT %s
                    """,
                    (KPI_AUDIT_SAMPLE_LIMIT,),
                )
                rows = await cur.fetchall()
                cur_pending = await conn.execute(
                    """
                    SELECT COUNT(*) AS n
                      FROM state_kv
                     WHERE key LIKE %s
                       AND value->>'status' = %s
                                             AND (
                                                 value#>>'{approval_context,expires_at}' IS NULL
                                                 OR (
                                                     value#>>'{approval_context,expires_at}' ~
                                                         '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
                                                     AND (
                                                         value#>>'{approval_context,expires_at}'
                                                     )::timestamptz > CURRENT_TIMESTAMP
                                                 )
                                             )
                    """,
                    (f"{PARK_KEY_PREFIX}%", DEFAULT_PENDING_STATUS),
                )
                pending_row = await cur_pending.fetchone()
        hil_pending = int(pending_row["n"]) if pending_row is not None else 0
        return aggregate_kpi(rows, hil_pending=hil_pending)

    async def list_hil_queue(
        self,
        *,
        limit: int = 50,
        search: str | None = None,
    ) -> HilQueuePage:
        bounded = clamp_limit(limit)
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cur = await conn.execute(
                    """
                    SELECT value, updated_at, COUNT(*) OVER() AS total_count
                      FROM state_kv
                     WHERE key LIKE %s
                       AND value->>'status' = %s
                                             AND (
                                                 value#>>'{approval_context,expires_at}' IS NULL
                                                 OR (
                                                     value#>>'{approval_context,expires_at}' ~
                                                         '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
                                                     AND (
                                                         value#>>'{approval_context,expires_at}'
                                                     )::timestamptz > CURRENT_TIMESTAMP
                                                 )
                                             )
                       AND (
                           %s IS NULL
                           OR CONCAT_WS(
                               ' ',
                               value->>'approval_id',
                               value->>'correlation_id',
                               value->>'action_type',
                               value->>'rule_id',
                               value#>>'{action,event_id}',
                               value#>>'{action,target_resource_ref}',
                               value#>>'{approval_context,reasons}',
                               value#>>'{action,citing_rules}'
                           ) ILIKE %s
                       )
                     ORDER BY
                       -- Cast `parked_at` to `timestamptz` so different UTC
                       -- offsets sort chronologically (raw string sort
                       -- would place `+09:00` behind `+00:00`). Guard the
                       -- cast with a regex so a malformed string (unlikely
                       -- - the coordinator writes `datetime.isoformat()`
                       -- - but not modelled at the schema level) falls
                       -- back to `updated_at` instead of raising and
                       -- blowing up the whole query.
                       CASE
                         WHEN value->>'parked_at' ~
                              '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
                         THEN (value->>'parked_at')::timestamptz
                         ELSE updated_at
                       END DESC
                     LIMIT %s
                    """,
                    (
                        f"{PARK_KEY_PREFIX}%",
                        DEFAULT_PENDING_STATUS,
                        search,
                        f"%{search}%" if search else None,
                        bounded,
                    ),
                )
                rows = await cur.fetchall()
        items: list[HilQueueItem] = []
        for row in rows:
            item = row_to_hil_queue_item(row)
            if item is not None:
                items.append(item)
        total = int(rows[0]["total_count"]) if rows else 0
        return HilQueuePage(items=tuple(items), total=total)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _set_statement_timeout(self, conn: psycopg.AsyncConnection[Any]) -> None:
        # SET LOCAL does not accept parametrized values in Postgres; inline
        # the (validated int) timeout literally.
        ms = int(self._config.statement_timeout_ms)
        await conn.execute(f"SET LOCAL statement_timeout = {ms}")


__all__ = [
    "DEFAULT_PENDING_STATUS",
    "PARK_KEY_PREFIX",
    "PostgresConsoleReadModel",
    "PostgresConsoleReadModelConfig",
    "aggregate_kpi",
    "row_to_audit_item",
    "row_to_hil_queue_item",
]
