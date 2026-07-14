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

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.read_api.read_model import (
    AuditItem,
    AuditPage,
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
INCIDENT_SUMMARY_HISTORY_LIMIT: Final[int] = 500

_INCIDENT_PAGE_SQL: Final[str] = """
WITH snapshot AS (
        SELECT COALESCE(%(snapshot_seq)s, MAX(seq), 0) AS snapshot_seq
            FROM audit_log
),
bounded_audit AS (
        SELECT * FROM audit_log
         WHERE seq <= (SELECT snapshot_seq FROM snapshot)
),
event_anchor AS (
    SELECT event_id, MIN(correlation_id) AS correlation_id
            FROM bounded_audit
     WHERE correlation_id IS NOT NULL AND correlation_id <> ''
     GROUP BY event_id
    HAVING COUNT(DISTINCT correlation_id) = 1
),
incident_open_raw AS (
    SELECT entry->>'incident_id' AS incident_id,
           COALESCE(
               correlation_id,
               (
                   SELECT CASE
                       WHEN COUNT(DISTINCT SUBSTRING(value FROM 6)) = 1
                       THEN MIN(SUBSTRING(value FROM 6))
                       ELSE NULL
                   END
                     FROM jsonb_array_elements_text(
                         CASE
                             WHEN jsonb_typeof(entry->'correlation_keys') = 'array'
                             THEN entry->'correlation_keys'
                             ELSE '[]'::jsonb
                         END
                     ) AS value
                    WHERE value LIKE 'corr:%%'
               )
           ) AS correlation_id
      FROM bounded_audit
     WHERE entry->>'kind' = 'incident.open'
),
incident_open AS (
    SELECT incident_id, MIN(correlation_id) AS correlation_id
      FROM incident_open_raw
     WHERE correlation_id IS NOT NULL AND correlation_id <> ''
     GROUP BY incident_id
    HAVING COUNT(DISTINCT correlation_id) = 1
),
normalized AS (
    SELECT a.*,
           COALESCE(a.correlation_id, ea.correlation_id, io.correlation_id)
               AS normalized_correlation_id,
           CASE
               WHEN a.entry->>'kind' = 'incident.transition' THEN a.entry->>'to_state'
               WHEN a.entry->>'kind' = 'incident.open' THEN a.entry->>'state'
               ELSE NULL
           END AS lifecycle_state
    FROM bounded_audit AS a
      LEFT JOIN event_anchor AS ea ON ea.event_id = a.event_id
      LEFT JOIN incident_open AS io ON io.incident_id = a.entry->>'incident_id'
),
ranked AS (
    SELECT normalized.*,
           ROW_NUMBER() OVER (
               PARTITION BY normalized_correlation_id ORDER BY seq DESC
           ) AS recent_rank,
           ROW_NUMBER() OVER (
               PARTITION BY normalized_correlation_id ORDER BY seq ASC
           ) AS oldest_rank,
           COUNT(*) OVER (
               PARTITION BY normalized_correlation_id
           ) AS group_history_count
      FROM normalized
),
incident_groups AS (
    SELECT normalized_correlation_id,
           MAX(seq) AS last_seq,
           COALESCE(
               (ARRAY_AGG(lifecycle_state ORDER BY seq DESC)
                   FILTER (WHERE lifecycle_state IS NOT NULL))[1],
               CASE
                   WHEN BOOL_OR(LOWER(COALESCE(entry->>'outcome', '')) IN (
                       'resolved', 'remediated', 'mitigated',
                       'rollback_succeeded', 'rollback_completed'
                   )) THEN 'resolved'
                   WHEN COUNT(*) > 1 OR BOOL_OR(
                       LOWER(COALESCE(entry->>'pipeline_stage', entry->>'stage', ''))
                           IN ('verify', 'gate', 'execute', 'escalate', 'hil')
                       OR LOWER(COALESCE(entry->>'decision', entry->>'gate_decision', '')) = 'hil'
                   ) THEN 'in_progress'
                   ELSE 'open'
               END
           ) AS projected_state
    FROM ranked
     WHERE normalized_correlation_id IS NOT NULL
       AND normalized_correlation_id <> ''
     GROUP BY normalized_correlation_id
),
selected AS (
    SELECT normalized_correlation_id, last_seq
      FROM incident_groups
    WHERE (%(before_seq)s IS NULL OR last_seq < %(before_seq)s)
       AND (
           %(status)s = 'all'
           OR (%(status)s = 'resolved' AND projected_state IN ('resolved', 'closed'))
           OR (%(status)s = 'active' AND projected_state NOT IN ('resolved', 'closed'))
       )
     ORDER BY last_seq DESC
     LIMIT %(fetch)s
)
SELECT n.seq, n.event_id, n.correlation_id, n.actor, n.action_kind,
       n.mode, n.entry, n.previous_hash, n.entry_hash, n.created_at,
         n.normalized_correlation_id, s.last_seq AS group_last_seq,
         n.group_history_count,
    (SELECT snapshot_seq FROM snapshot) AS snapshot_seq
  FROM selected AS s
  JOIN ranked AS n
    ON n.normalized_correlation_id = s.normalized_correlation_id
 WHERE n.recent_rank <= %(summary_history_limit)s
     OR n.oldest_rank = 1
     OR n.lifecycle_state IS NOT NULL
 ORDER BY s.last_seq DESC, n.seq ASC
"""


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


def _parse_cursor(cursor: str | None) -> int | None:
    """Decode an opaque cursor into a ``seq`` cutoff, or ``None`` for page 1.

    The cursor from :meth:`PostgresConsoleReadModel.list_audit` is the
    ``seq`` of the last row on the previous page. A newer row has a
    higher ``seq``; "next page" means strictly smaller ``seq``.
    """
    if cursor is None or cursor == "":
        return None
    try:
        return int(cursor)
    except ValueError as exc:
        raise ValueError(f"invalid cursor: {cursor!r}") from exc


def row_to_audit_item(row: Mapping[str, Any]) -> AuditItem:
    """Map a raw ``audit_log`` row to :class:`AuditItem`.

    Pure function so the mapping is unit-testable without a live DB.
    ``entry`` may arrive as a ``dict`` (psycopg auto-decodes JSONB) or
    a raw ``str`` (fallback); either shape is normalized to a mapping.
    """
    entry_raw = row["entry"]
    if isinstance(entry_raw, str):
        entry = json.loads(entry_raw)
    elif isinstance(entry_raw, Mapping):
        entry = dict(entry_raw)
    else:
        raise TypeError(f"audit_log.entry MUST be JSONB (dict|str); got {type(entry_raw).__name__}")
    correlation_id = row.get("correlation_id")
    return AuditItem(
        seq=int(row["seq"]),
        event_id=str(row["event_id"]),
        correlation_id=str(correlation_id) if correlation_id is not None else None,
        actor=str(row["actor"]),
        action_kind=str(row["action_kind"]),
        mode=str(row["mode"]),
        entry=entry,
        entry_hash=str(row["entry_hash"]),
        previous_hash=str(row["previous_hash"]),
        recorded_at=_isoformat(row["created_at"]),
    )


def row_to_hil_queue_item(row: Mapping[str, Any]) -> HilQueueItem | None:
    """Map one ``state_kv`` HIL park row to :class:`HilQueueItem`.

    Returns ``None`` when the row is missing required fields - HIL park
    records evolve over time and a defensive projection is safer than a
    hard failure on a legacy shape.
    """
    value_raw = row["value"]
    if isinstance(value_raw, str):
        try:
            parked = json.loads(value_raw)
        except (TypeError, ValueError):
            return None
    elif isinstance(value_raw, Mapping):
        parked = dict(value_raw)
    else:
        return None
    approval_id = parked.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id:
        return None
    parked_at = parked.get("parked_at")
    if not isinstance(parked_at, str) or not parked_at:
        return None
    action = parked.get("action") if isinstance(parked.get("action"), Mapping) else {}
    idempotency_key = parked.get("idempotency_key") or action.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        return None
    # `action` is always a Mapping by the branch above (either the parked
    # `action` dict or the empty-dict fallback) - no `isinstance` guard
    # needed on the reads below.
    event_id = action.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        event_id = "00000000-0000-0000-0000-000000000000"
    action_type = parked.get("action_type") or action.get("action_type")
    rule_id = parked.get("rule_id")
    reason_bits: list[str] = []
    if isinstance(rule_id, str) and rule_id:
        reason_bits.append(f"rule:{rule_id}")
    submitter = parked.get("submitter_oid")
    if isinstance(submitter, str) and submitter:
        reason_bits.append(f"submitter:{submitter}")
    reason = " ".join(reason_bits) if reason_bits else "hil.requested"
    correlation_id = parked.get("correlation_id")
    return HilQueueItem(
        idempotency_key=idempotency_key,
        event_id=event_id,
        action_kind=str(action_type) if action_type else "unknown",
        reason=reason,
        requested_at=parked_at,
        correlation_id=(
            str(correlation_id) if isinstance(correlation_id, str) and correlation_id else None
        ),
    )


def _isoformat(value: Any) -> str:
    """Best-effort ISO-8601 string for a psycopg ``TIMESTAMPTZ`` value."""
    if value is None:
        return ""
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def aggregate_kpi(
    rows: Sequence[Mapping[str, Any]],
    *,
    hil_pending: int,
) -> DashboardKpi:
    """Compute :class:`DashboardKpi` from a page of ``audit_log`` rows.

    Pure function; the DB path calls this after materializing the row set.
    Mirrors :class:`InMemoryConsoleReadModel.dashboard_metrics` so the two
    backends produce identical shapes for the same input.
    """
    total = len(rows)
    if total == 0:
        return DashboardKpi(
            event_count=0,
            shadow_share=0.0,
            enforce_share=0.0,
            hil_pending=hil_pending,
            by_action_kind={},
            by_outcome={},
            by_tier={},
            last_recorded_at=None,
        )
    by_kind: dict[str, int] = {}
    by_outcome: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    shadow = 0
    enforce = 0
    # Track the latest `created_at` seen (ordered comparison on the raw
    # value, not on the ISO string). The Postgres path passes rows in
    # ``ORDER BY seq DESC`` (newest first), so a naive "last iteration
    # wins" would return the OLDEST recorded_at - the exact opposite of
    # what the KPI panel expects. Comparing the raw ``datetime`` (or
    # falling back to the ISO string when it is missing) keeps the
    # aggregator independent of caller-side row order.
    latest_raw: Any = None
    latest_iso: str | None = None
    for row in rows:
        action_kind = str(row.get("action_kind", "unknown"))
        by_kind[action_kind] = by_kind.get(action_kind, 0) + 1
        entry_raw = row.get("entry", {})
        if isinstance(entry_raw, str):
            try:
                entry = json.loads(entry_raw)
            except (TypeError, ValueError):
                entry = {}
        elif isinstance(entry_raw, Mapping):
            entry = dict(entry_raw)
        else:
            entry = {}
        outcome = str(entry.get("outcome", "unknown"))
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        tier = entry.get("tier")
        if tier is not None:
            tier_key = str(tier)
            by_tier[tier_key] = by_tier.get(tier_key, 0) + 1
        mode = str(row.get("mode", ""))
        if mode == "shadow":
            shadow += 1
        elif mode == "enforce":
            enforce += 1
        raw_at = row.get("created_at")
        if raw_at is None:
            continue
        # `datetime` comparisons are total when both sides are aware or
        # both naive; mixing raises. Coerce comparability by falling back
        # to ISO string when the current row cannot be compared with the
        # running max (defensive - the schema keeps created_at TIMESTAMPTZ).
        try:
            if latest_raw is None or raw_at > latest_raw:
                latest_raw = raw_at
                latest_iso = _isoformat(raw_at)
        except TypeError:
            iso = _isoformat(raw_at)
            if iso and (latest_iso is None or iso > latest_iso):
                latest_raw = raw_at
                latest_iso = iso
    return DashboardKpi(
        event_count=total,
        shadow_share=shadow / total,
        enforce_share=enforce / total,
        hil_pending=hil_pending,
        by_action_kind=by_kind,
        by_outcome=by_outcome,
        by_tier=by_tier,
        last_recorded_at=latest_iso,
    )


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
                if correlation_id is not None and cutoff is None:
                    cur = await conn.execute(
                        """
                        WITH unambiguous_events AS (
                            SELECT event_id FROM audit_log GROUP BY event_id
                            HAVING COUNT(DISTINCT correlation_id)
                                FILTER (WHERE correlation_id IS NOT NULL) = 1
                               AND MIN(correlation_id)
                                FILTER (WHERE correlation_id IS NOT NULL) = %s
                        )
                        SELECT seq, event_id, correlation_id, actor, action_kind,
                               mode, entry, previous_hash, entry_hash, created_at
                          FROM audit_log
                         WHERE correlation_id = %s
                            OR event_id IN (SELECT event_id FROM unambiguous_events)
                         ORDER BY seq DESC
                         LIMIT %s
                        """,
                        (correlation_id, correlation_id, fetch),
                    )
                elif correlation_id is not None:
                    cur = await conn.execute(
                        """
                        WITH unambiguous_events AS (
                            SELECT event_id FROM audit_log GROUP BY event_id
                            HAVING COUNT(DISTINCT correlation_id)
                                FILTER (WHERE correlation_id IS NOT NULL) = 1
                               AND MIN(correlation_id)
                                FILTER (WHERE correlation_id IS NOT NULL) = %s
                        )
                        SELECT seq, event_id, correlation_id, actor, action_kind,
                               mode, entry, previous_hash, entry_hash, created_at
                          FROM audit_log
                         WHERE seq < %s
                           AND (correlation_id = %s
                                OR event_id IN (SELECT event_id FROM unambiguous_events))
                         ORDER BY seq DESC
                         LIMIT %s
                        """,
                        (correlation_id, cutoff, correlation_id, fetch),
                    )
                elif cutoff is None:
                    cur = await conn.execute(
                        """
                        SELECT seq, event_id, correlation_id, actor, action_kind,
                               mode, entry, previous_hash, entry_hash, created_at
                          FROM audit_log
                         ORDER BY seq DESC
                         LIMIT %s
                        """,
                        (fetch,),
                    )
                else:
                    cur = await conn.execute(
                        """
                        SELECT seq, event_id, correlation_id, actor, action_kind,
                               mode, entry, previous_hash, entry_hash, created_at
                          FROM audit_log
                         WHERE seq < %s
                         ORDER BY seq DESC
                         LIMIT %s
                        """,
                        (cutoff, fetch),
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
    ) -> IncidentPage:
        """Return a bounded incident roster derived from the audit ledger."""

        from fdai.delivery.read_api.routes.incident_projection import project_incidents

        if status not in {"active", "resolved", "all"}:
            raise ValueError(f"invalid incident status filter: {status!r}")
        bounded = clamp_limit(limit)
        decoded = decode_incident_cursor(cursor, status=status)
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
                )
            )
            if len(group_order) > bounded and visible_correlations
            else None
        )
        return IncidentPage(items=items, next_cursor=next_cursor)

    async def dashboard_metrics(self) -> DashboardKpi:
        # KPI is scoped to the most recent window so the aggregation is
        # bounded regardless of how large the audit log grows. The
        # in-memory reference model aggregates over every stored row;
        # the Postgres path bounds the scan with an explicit LIMIT that
        # matches the ``clamp_limit`` ceiling used by ``list_audit`` so
        # a KPI page and an audit page reason about the same window.
        window = clamp_limit(None) * 10  # up to 500 rows, matching MAX_LIMIT
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cur = await conn.execute(
                    """
                    SELECT action_kind, mode, entry, created_at
                      FROM audit_log
                     ORDER BY seq DESC
                     LIMIT %s
                    """,
                    (window,),
                )
                rows = await cur.fetchall()
                cur_pending = await conn.execute(
                    """
                    SELECT COUNT(*) AS n
                      FROM state_kv
                     WHERE key LIKE %s
                       AND value->>'status' = %s
                    """,
                    (f"{PARK_KEY_PREFIX}%", DEFAULT_PENDING_STATUS),
                )
                pending_row = await cur_pending.fetchone()
        hil_pending = int(pending_row["n"]) if pending_row is not None else 0
        return aggregate_kpi(rows, hil_pending=hil_pending)

    async def list_hil_queue(self, *, limit: int = 50) -> HilQueuePage:
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
                    (f"{PARK_KEY_PREFIX}%", DEFAULT_PENDING_STATUS, bounded),
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
