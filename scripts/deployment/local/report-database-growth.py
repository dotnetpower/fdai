#!/usr/bin/env python3
"""Report local database size, the largest tables, and lifecycle retention status.

Read-only. Only loopback port 5432 database ``fdai`` is accepted, and no connection value is
printed. Warnings are based on unpruned cold audit rows, dead-tuple backlog, expired cache rows,
and unreachable state rather than a byte-size limit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_DSN_ENV = "FDAI_STATE_STORE_DSN"
_SAMPLE_PATH = Path(".fdai/local-db-growth.json")
DEAD_ROW_WARN_THRESHOLD = 10_000
COLD_AUDIT_ROW_WARN_THRESHOLD = 50_000
HEIMDALL_VERSION_WARN_THRESHOLD = 5_000
_MIB = 1024 * 1024
_CONNECTION_OPTIONS = "-c statement_timeout=10000 -c lock_timeout=1000"
_STATE_FAMILY_SQL = """
SELECT family, count(*) AS rows, sum(value_bytes) AS value_bytes,
       max(value_bytes) AS largest_value_bytes
FROM (
    SELECT CASE
        WHEN starts_with(key, 'baseline-evaluation:outcomes:') THEN 'baseline_outcomes'
        WHEN starts_with(key, 'baseline-evaluation:completions:') THEN 'baseline_completions'
        WHEN starts_with(key, 'pantheon/forseti/no-rule-fold|') THEN 'forseti_no_rule'
        WHEN starts_with(key, 'pantheon/heimdall/sensing-state/buckets/') THEN 'heimdall_buckets'
        WHEN starts_with(key, 'pantheon/heimdall/sensing-state/episodes/') THEN 'heimdall_episodes'
        WHEN starts_with(key, 'pantheon/heimdall/sensing-state/readiness-pending/')
            THEN 'heimdall_pending_readiness'
        WHEN starts_with(key, 'pantheon/heimdall/sensing-state/readiness/')
            THEN 'heimdall_readiness'
        WHEN starts_with(key, 'pantheon/heimdall/sensing-state/versions/')
            THEN 'heimdall_versions'
        WHEN starts_with(key, 'pantheon/heimdall/sensing-state/manifests/')
            THEN 'heimdall_manifests'
        WHEN starts_with(key, 'pantheon/heimdall/publications/') THEN 'heimdall_publications'
        WHEN starts_with(key, 'pantheon/heimdall/') THEN 'heimdall_recovery'
        WHEN starts_with(key, 'pantheon/huginn/ingress-dedup/') THEN 'huginn_ingress_dedup'
        WHEN key = 'pantheon/saga/audit-chain/verified-head' THEN 'saga_audit_checkpoint'
        WHEN key = 'pantheon/saga/verdict-aggregate-pending' THEN 'saga_verdict_aggregate'
        WHEN starts_with(key, 'pantheon/saga') THEN 'saga_recovery'
        WHEN starts_with(key, 'measurement:control-loop:') THEN 'control_loop_measurements'
        WHEN starts_with(key, 'aks-diagnostic-receipt:v1:') THEN 'aks_diagnostics'
        WHEN starts_with(key, 'inventory') THEN 'inventory_state'
        WHEN starts_with(key, 'ontology') THEN 'ontology_state'
        WHEN starts_with(key, 'operator-projection:') THEN 'operator_projections'
        WHEN starts_with(key, 'operator-semantic') THEN 'operator_semantic'
        WHEN starts_with(key, 'semantic-turn:') THEN 'semantic_turn'
        ELSE 'other'
    END AS family, pg_column_size(value) AS value_bytes FROM state_kv
) classified
GROUP BY family ORDER BY value_bytes DESC, family
"""
_AUDIT_FAMILY_SQL = """
SELECT action_kind, count(*), COALESCE(sum(pg_column_size(entry)), 0)
  FROM audit_log GROUP BY action_kind ORDER BY 3 DESC, action_kind LIMIT 8
"""
_TABLE_STORAGE_SQL = """
SELECT n.nspname, c.relname, c.oid,
       pg_total_relation_size(c.oid) AS total_bytes,
       pg_indexes_size(c.oid) AS index_bytes,
       CASE WHEN c.reltoastrelid = 0 THEN 0
            ELSE pg_total_relation_size(c.reltoastrelid) END AS toast_bytes,
       COALESCE(s.n_live_tup, 0), COALESCE(s.n_dead_tup, 0),
       COALESCE(s.n_tup_ins, 0), COALESCE(s.n_tup_upd, 0),
       COALESCE(s.n_tup_del, 0), COALESCE(s.n_tup_hot_upd, 0),
       s.last_autovacuum, s.last_autoanalyze
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
 WHERE c.relkind IN ('r', 'm')
   AND n.nspname NOT IN ('pg_catalog', 'information_schema')
   AND n.nspname NOT LIKE 'pg_toast%%' AND n.nspname NOT LIKE 'pg_temp_%%'
 ORDER BY pg_total_relation_size(c.oid) DESC, n.nspname, c.relname
"""
_INDEX_STORAGE_SQL = """
SELECT n.nspname, t.relname, c.relname, pg_relation_size(c.oid),
       COALESCE(s.idx_scan, 0), i.indisunique, i.indisprimary
  FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
  JOIN pg_class t ON t.oid = i.indrelid
  JOIN pg_namespace n ON n.oid = t.relnamespace
  LEFT JOIN pg_stat_user_indexes s ON s.indexrelid = c.oid
 WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
   AND n.nspname NOT LIKE 'pg_toast%%' AND n.nspname NOT LIKE 'pg_temp_%%'
 ORDER BY pg_relation_size(c.oid) DESC, n.nspname, c.relname
 LIMIT %s
"""


def growth_per_hour(previous: dict[str, Any] | None, size_bytes: int, now: float) -> float | None:
    """Return bytes per hour since the previous sample, or ``None`` without a usable one."""
    if not previous:
        return None
    elapsed = now - float(previous.get("at", now))
    if elapsed < 60:
        return None
    return (size_bytes - int(previous.get("size_bytes", size_bytes))) / elapsed * 3600


def lifecycle_warnings(
    tables: list[dict[str, Any]], details: dict[str, Any] | None = None
) -> list[str]:
    """Warn on unpruned cold audit rows, dead-tuple backlog, or expired state, never byte size."""
    warnings: list[str] = []
    for table in tables:
        relation = str(table.get("relation") or "")
        live = int(table.get("estimated_live_rows") or 0)
        dead = int(table.get("estimated_dead_rows") or 0)
        if dead >= DEAD_ROW_WARN_THRESHOLD and dead > live:
            warnings.append(
                f"{relation} has {dead:,} dead rows exceeding {live:,} live rows; "
                "run compact-local-database.py --apply --vacuum"
            )
        if relation == "public.audit_log" and live >= COLD_AUDIT_ROW_WARN_THRESHOLD:
            warnings.append(
                f"public.audit_log has {live:,} live rows; "
                "run archive-audit-segments.py --prune to archive and anchor cold segments"
            )
    if isinstance(details, dict):
        for cache_table in ("t2_cache", "t2_cache_legacy_default"):
            entry = details.get(cache_table)
            expired = int(entry.get("expired_rows") or 0) if isinstance(entry, dict) else 0
            if expired > 0:
                warnings.append(
                    f"{cache_table} has {expired:,} expired rows; "
                    "run compact-local-database.py --apply"
                )
        families = details.get("state_families")
        if isinstance(families, list):
            for family in families:
                if (
                    isinstance(family, dict)
                    and family.get("family") == "heimdall_versions"
                    and int(family.get("rows") or 0) >= HEIMDALL_VERSION_WARN_THRESHOLD
                ):
                    count = int(family["rows"])
                    warnings.append(
                        f"heimdall_versions has {count:,} rows; "
                        "run compact-local-database.py --apply"
                    )
    return warnings


def assess_lifecycle(warnings: list[str]) -> str:
    """Return ``warn`` when lifecycle cleanup is needed and ``ok`` otherwise."""
    return "warn" if warnings else "ok"


def table_storage(row: tuple[Any, ...]) -> dict[str, Any]:
    total, indexes, toast = (int(value) for value in row[3:6])
    if min(total, indexes, toast) < 0 or indexes + toast > total:
        raise RuntimeError("relation sizes changed during sampling; run a fresh storage report")
    return {
        "relation": f"{row[0]}.{row[1]}",
        "oid": int(row[2]),
        "total_bytes": total,
        "heap_bytes": total - indexes - toast,
        "index_bytes": indexes,
        "toast_bytes": toast,
        "estimated_live_rows": int(row[6]),
        "estimated_dead_rows": int(row[7]),
        "inserts": int(row[8]),
        "updates": int(row[9]),
        "deletes": int(row[10]),
        "hot_updates": int(row[11]),
        "last_autovacuum": row[12].isoformat() if row[12] is not None else None,
        "last_autoanalyze": row[13].isoformat() if row[13] is not None else None,
    }


def relation_growth(
    previous: dict[str, Any] | None, table: dict[str, Any], now: float
) -> float | None:
    if not previous or not isinstance(previous.get("relations"), dict):
        return None
    prior = previous["relations"].get(table["relation"])
    if not isinstance(prior, dict) or prior.get("oid") != table["oid"]:
        return None
    return growth_per_hour(
        {"at": previous["at"], "size_bytes": prior["total_bytes"]}, table["total_bytes"], now
    )


def _relation_read_status(connection: Any, relation: str) -> str:
    exists = connection.execute("SELECT to_regclass(%s)", (relation,)).fetchone()
    if exists is None:
        raise RuntimeError("database growth report returned no relation accounting")
    if exists[0] is None:
        return "not_installed"
    access = connection.execute(
        "SELECT has_table_privilege(current_user, %s::regclass, 'SELECT')", (relation,)
    ).fetchone()
    if access is None:
        raise RuntimeError("database growth report returned no relation access accounting")
    return "available" if access[0] else "select_permission_required"


def storage_details(connection: Any) -> dict[str, Any]:
    """Measure fixed known storage families without returning any stored content."""
    details: dict[str, Any] = {}
    for relation, column in (
        ("conversation_image", "content"),
        ("trusted_artifact", "artifact"),
    ):
        status = _relation_read_status(connection, relation)
        if status == "available":
            row = connection.execute(
                sql.SQL("SELECT count(*), COALESCE(sum(octet_length({})), 0) FROM {}").format(
                    sql.Identifier(column), sql.Identifier(relation)
                )
            ).fetchone()
            details[relation] = {"rows": int(row[0]), "payload_bytes": int(row[1])}
        else:
            details[relation] = {"status": status}
    for relation in ("t2_cache", "t2_cache_legacy_default"):
        status = _relation_read_status(connection, relation)
        if status == "available":
            row = connection.execute(
                sql.SQL(
                    "SELECT count(*), count(*) FILTER (WHERE expires_at <= CURRENT_TIMESTAMP) "
                    "FROM {}"
                ).format(sql.Identifier(relation))
            ).fetchone()
            details[relation] = {
                "rows": int(row[0]),
                "expired_rows": int(row[1]),
            }
        else:
            details[relation] = {"status": status}
    policy_status = _relation_read_status(connection, "operational_retention_policy")
    if policy_status == "available":
        rows = connection.execute(
            "SELECT fact_family, deletion_method, review_at "
            "FROM operational_retention_policy ORDER BY fact_family, policy_digest"
        ).fetchall()
        details["retention_policies"] = [
            {"fact_family": row[0], "deletion_method": row[1], "review_at": row[2].isoformat()}
            for row in rows
        ]
    else:
        details["retention_policies"] = {"status": policy_status}
    state_status = _relation_read_status(connection, "state_kv")
    if state_status == "available":
        rows = connection.execute(_STATE_FAMILY_SQL).fetchall()
        details["state_families"] = [
            {
                "family": row[0],
                "rows": int(row[1]),
                "value_storage_bytes": int(row[2]),
                "largest_value_bytes": int(row[3]),
            }
            for row in rows
        ]
    else:
        details["state_families"] = {"status": state_status}
    audit_status = _relation_read_status(connection, "audit_log")
    if audit_status == "available":
        details["audit_families"] = [
            {"action_kind": row[0], "rows": int(row[1]), "entry_storage_bytes": int(row[2])}
            for row in connection.execute(_AUDIT_FAMILY_SQL).fetchall()
        ]
    else:
        details["audit_families"] = {"status": audit_status}
    statistics = connection.execute(
        "SELECT stats_reset, tup_inserted, tup_updated, tup_deleted, "
        "blk_read_time, blk_write_time FROM pg_stat_database "
        "WHERE datname=current_database()"
    ).fetchone()
    if statistics is None:
        raise RuntimeError("database growth report returned no write statistics")
    details["database_activity"] = {
        "stats_reset": statistics[0].isoformat() if statistics[0] is not None else None,
        "inserted_rows": int(statistics[1]),
        "updated_rows": int(statistics[2]),
        "deleted_rows": int(statistics[3]),
        "block_read_time_ms": float(statistics[4]),
        "block_write_time_ms": float(statistics[5]),
        "timing_requires_track_io_timing": True,
    }
    return details


def _dsn() -> str:
    raw = os.environ.get(_DSN_ENV, "").strip()
    if not raw:
        raise SystemExit(f"{_DSN_ENV} is not set; source .fdai/local-runtime.env first")
    dsn = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    info = conninfo_to_dict(dsn)
    if (
        str(info.get("host") or "") not in _LOOPBACK_HOSTS
        or str(info.get("port") or "5432") != "5432"
        or str(info.get("dbname") or "") != "fdai"
    ):
        raise SystemExit("database growth report requires loopback port 5432 and database fdai")
    return dsn


def _previous_sample(database_oid: int) -> dict[str, Any] | None:
    if not _SAMPLE_PATH.is_file():
        return None
    try:
        loaded = json.loads(_SAMPLE_PATH.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("database growth sample must contain a JSON object")
        if loaded.get("database_oid") != database_oid:
            return None
        if (
            not isinstance(loaded.get("at"), (int, float))
            or not isinstance(loaded.get("size_bytes"), int)
            or not isinstance(loaded.get("relations"), dict)
        ):
            raise ValueError("database growth sample has invalid accounting")
        for relation in loaded["relations"].values():
            if not isinstance(relation, dict) or not all(
                isinstance(relation.get(field), int) for field in ("oid", "total_bytes")
            ):
                raise ValueError("database growth sample has invalid relation accounting")
        return loaded
    except (OSError, ValueError):
        print(
            "WARNING: previous database growth sample is unreadable; baseline reset",
            file=sys.stderr,
        )
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=5, help="number of largest tables to list")
    parser.add_argument("--no-sample", action="store_true", help="do not record this size sample")
    parser.add_argument(
        "--json", action="store_true", help="emit aggregate storage metadata as JSON"
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="also measure binary payloads, cache expiry and policies",
    )
    args = parser.parse_args()
    top = max(1, min(args.top, 20))
    with psycopg.connect(_dsn(), connect_timeout=5, options=_CONNECTION_OPTIONS) as connection:
        connection.execute("SET default_transaction_read_only = on")
        connection.execute("SET TRANSACTION READ ONLY")
        size_row = connection.execute("SELECT pg_database_size(current_database())").fetchone()
        database_row = connection.execute(
            "SELECT oid FROM pg_database WHERE datname=current_database()"
        ).fetchone()
        if size_row is None or database_row is None:
            raise RuntimeError("database growth report returned no database accounting")
        size, database_oid = int(size_row[0]), int(database_row[0])
        tables = [table_storage(row) for row in connection.execute(_TABLE_STORAGE_SQL).fetchall()]
        indexes = connection.execute(_INDEX_STORAGE_SQL, (top,)).fetchall()
        stats_row = connection.execute(
            "SELECT stats_reset FROM pg_stat_database WHERE datname=current_database()"
        ).fetchone()
        if stats_row is None:
            raise RuntimeError("database growth report returned no statistics accounting")
        stats_reset = stats_row[0]
        details = storage_details(connection) if args.details else None
    now = time.time()
    previous = _previous_sample(database_oid)
    rate = growth_per_hour(previous, size, now)
    warnings = lifecycle_warnings(tables, details)
    status = assess_lifecycle(warnings)
    for table in tables:
        table["growth_bytes_per_hour"] = relation_growth(previous, table, now)
    report = {
        "size_bytes": size,
        "status": status,
        "growth_bytes_per_hour": rate,
        "lifecycle_warnings": warnings,
        "tables": tables[:top],
        "indexes": [
            {
                "relation": f"{row[0]}.{row[1]}",
                "index": row[2],
                "bytes": int(row[3]),
                "scans_since_stats_reset": int(row[4]),
                "unique": bool(row[5]),
                "primary": bool(row[6]),
            }
            for row in indexes
        ],
        "stats_reset": stats_reset.isoformat() if stats_reset is not None else None,
        "details": details,
        "details_complete": details is None
        or not any(
            isinstance(value, dict) and value.get("status") == "select_permission_required"
            for value in details.values()
        ),
    }
    if args.json:
        print(json.dumps(report))
    else:
        print(f"size:   {size / _MIB:,.0f} MiB (lifecycle status: {status})")
        if rate is not None:
            print(f"growth: {rate / _MIB:+,.1f} MiB/hour since the previous report")
        for table in tables[:top]:
            print(
                f"  {table['relation']:<46} {table['total_bytes'] / _MIB:>8,.1f} MiB "
                f"heap={table['heap_bytes'] / _MIB:.1f} index={table['index_bytes'] / _MIB:.1f} "
                f"toast={table['toast_bytes'] / _MIB:.1f} "
                f"dead_rows_estimate={table['estimated_dead_rows']}"
            )
        if details is not None:
            print(json.dumps(details, sort_keys=True))
    if warnings and not args.json:
        for warning in warnings:
            print(f"WARNING: {warning}")
    if not args.no_sample:
        _SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SAMPLE_PATH.write_text(
            json.dumps(
                {
                    "at": now,
                    "size_bytes": size,
                    "database_oid": database_oid,
                    "relations": {
                        table["relation"]: {
                            "oid": table["oid"],
                            "total_bytes": table["total_bytes"],
                        }
                        for table in tables
                    },
                }
            ),
            encoding="utf-8",
        )
    return 0 if report["details_complete"] else 2


if __name__ == "__main__":
    sys.exit(main())
