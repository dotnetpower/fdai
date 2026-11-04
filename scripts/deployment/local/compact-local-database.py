#!/usr/bin/env python3
"""Apply the state retention bounds to the loopback development database.

The default run only reports how many rows each bound would remove. ``--apply`` deletes the
oldest rows past each bound, using the same newest-N windows the running services use, removes
Heimdall checkpoint rows the stored root cannot reach (older than one hour only), and
``--vacuum`` runs ordinary vacuum; ``--vacuum-full`` explicitly requests a table rewrite.
Only loopback port 5432 database
``fdai`` is accepted, and no connection value is printed. Evidence tables, the audit log, and
the inventory journal are never touched.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime

import psycopg
from fdai.agents import (
    BASELINE_EVALUATION_COMPLETION_PREFIX,
    BASELINE_EVALUATION_MIN_RETENTION,
    BASELINE_EVALUATION_OUTCOME_PREFIX,
    NO_RULE_FOLD_PREFIX,
    NO_RULE_FOLD_RETENTION,
)
from fdai.agents._framework.heimdall_checkpoint_gc import (
    MIN_ROW_AGE,
    SCANNED_PREFIXES,
    reachable_from_store,
)
from fdai.delivery.aks_diagnostic_receipts import (
    AKS_DIAGNOSTIC_RECEIPT_PREFIX,
    AKS_DIAGNOSTIC_RECEIPT_RETENTION,
)
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from psycopg.conninfo import conninfo_to_dict

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_DSN_ENV = "FDAI_STATE_STORE_DSN"
_OWNER_DSN_ENV = "FDAI_DATABASE_URL"
_CONNECT_TIMEOUT_SECONDS = 5
_CONNECTION_OPTIONS = "-c statement_timeout=30000 -c lock_timeout=1000"
_CHECKPOINT_BATCH = 2_000
# Disposable evidence rows whose audit summary is retained elsewhere: newest-N windows that no
# running service bounds. An optional (field, value) pair limits a window to finished rows.
# Publication fences such as analyzer-publication rows are never listed: deleting one could
# republish a record the broker already holds.
_LOCAL_WINDOWS: dict[str, tuple[int, tuple[str, str] | None]] = {
    "hil_park:": (500, ("status", "resolved")),
}
_UNREACHABLE_USAGE_SQL = (
    "SELECT count(*), COALESCE(sum(pg_column_size(value)), 0) FROM state_kv "
    "WHERE starts_with(key, %s) AND updated_at < %s AND NOT (key = ANY(%s))"
)
_UNREACHABLE_DELETE_SQL = (
    "DELETE FROM state_kv WHERE key IN (SELECT key FROM state_kv "
    "WHERE starts_with(key, %s) AND updated_at < %s AND NOT (key = ANY(%s)) "
    "ORDER BY key LIMIT %s)"
)


def _dsn(variable: str = _DSN_ENV) -> str:
    raw = os.environ.get(variable, "").strip()
    if not raw:
        raise SystemExit(f"{variable} is not set; source .fdai/local-runtime.env first")
    dsn = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    info = conninfo_to_dict(dsn)
    if (
        str(info.get("host") or "") not in _LOOPBACK_HOSTS
        or str(info.get("port") or "5432") != "5432"
        or str(info.get("dbname") or "") != "fdai"
    ):
        raise SystemExit("database compaction requires loopback port 5432 and database fdai")
    return dsn


def _usage(dsn: str, prefix: str, keep: int) -> dict[str, int]:
    with psycopg.connect(
        dsn, connect_timeout=_CONNECT_TIMEOUT_SECONDS, options=_CONNECTION_OPTIONS
    ) as connection:
        connection.execute("SET default_transaction_read_only = on")
        window_filter = _LOCAL_WINDOWS.get(prefix, (0, None))[1]
        row = connection.execute(
            "SELECT count(*), COALESCE(sum(value_bytes), 0), "
            "COALESCE(sum(value_bytes) FILTER (WHERE retained_rank <= %s), 0) FROM ("
            "SELECT pg_column_size(value) AS value_bytes, "
            "row_number() OVER (ORDER BY updated_at DESC, key DESC) AS retained_rank "
            "FROM state_kv WHERE key LIKE %s ESCAPE '\\' "
            "AND (%s::text IS NULL OR value->>%s = %s)) AS ranked",
            (
                keep,
                prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",
                window_filter[1] if window_filter else None,
                window_filter[0] if window_filter else "",
                window_filter[1] if window_filter else "",
            ),
        ).fetchone()
    if row is None:
        raise RuntimeError("database compaction usage query returned no result")
    return {
        "rows": int(row[0]),
        "value_storage_bytes": int(row[1]),
        "retained_value_storage_bytes": int(row[2]),
    }


def _bounds(dsn: str) -> dict[str, int]:
    # The covered generation is whole in the newest window, so keep two of them.
    with psycopg.connect(
        dsn, connect_timeout=_CONNECT_TIMEOUT_SECONDS, options=_CONNECTION_OPTIONS
    ) as connection:
        connection.execute("SET default_transaction_read_only = on")
        latest = connection.execute(
            "SELECT COALESCE(MAX((value->>'expected_denominator')::int), 0) "
            "FROM state_kv WHERE key LIKE %s",
            (BASELINE_EVALUATION_COMPLETION_PREFIX + "%",),
        ).fetchone()
    largest = int(latest[0]) if latest else 0
    return {
        BASELINE_EVALUATION_OUTCOME_PREFIX: max(2 * largest, BASELINE_EVALUATION_MIN_RETENTION),
        NO_RULE_FOLD_PREFIX: NO_RULE_FOLD_RETENTION,
        AKS_DIAGNOSTIC_RECEIPT_PREFIX: AKS_DIAGNOSTIC_RECEIPT_RETENTION,
        **{prefix: keep for prefix, (keep, _filter) in _LOCAL_WINDOWS.items()},
    }


class _ConnectionStateReader:
    """Read exact state rows over the maintenance connection without constructing a writer."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    async def read_state(self, key: str) -> dict[str, object] | None:
        row = self._connection.execute(
            "SELECT value FROM state_kv WHERE key = %s", (key,)
        ).fetchone()
        return row[0] if row is not None and isinstance(row[0], dict) else None


async def _heimdall_checkpoint(dsn: str, *, apply: bool) -> dict[str, object]:
    """Report or delete superseded Heimdall checkpoint rows the stored root cannot reach.

    Reachability is traversed from the stored root exactly as recovery reads it, and only rows
    untouched for the minimum age are eligible, so a running writer's unpublished rows are safe.
    """
    prefixes: dict[str, dict[str, int]] = {}
    with psycopg.connect(
        dsn, connect_timeout=_CONNECT_TIMEOUT_SECONDS, options=_CONNECTION_OPTIONS
    ) as connection:
        if not apply:
            connection.execute("SET default_transaction_read_only = on")
        reachable = await reachable_from_store(_ConnectionStateReader(connection))
        if reachable is None:
            return {"status": "unverifiable", "reason": "no_verifiable_versioned_checkpoint"}
        connection.commit()
        cutoff = datetime.now(tz=UTC) - MIN_ROW_AGE
        keep = sorted(reachable)
        for prefix in SCANNED_PREFIXES:
            row = connection.execute(_UNREACHABLE_USAGE_SQL, (prefix, cutoff, keep)).fetchone()
            if row is None:
                raise RuntimeError("heimdall checkpoint usage query returned no result")
            entry = {
                "reclaimable_rows": int(row[0]),
                "reclaimable_value_storage_bytes": int(row[1]),
            }
            if apply:
                deleted = 0
                while True:
                    removed = connection.execute(
                        _UNREACHABLE_DELETE_SQL, (prefix, cutoff, keep, _CHECKPOINT_BATCH)
                    ).rowcount
                    connection.commit()
                    if removed < 1:
                        break
                    deleted += removed
                entry["deleted"] = deleted
            prefixes[prefix] = entry
    return {"status": "ready", "reachable_rows": len(reachable), "prefixes": prefixes}


async def _run(
    *,
    apply: bool,
    vacuum: bool,
    vacuum_full: bool = False,
    max_prefix_bytes: int | None = None,
) -> dict[str, object]:
    if max_prefix_bytes is not None and max_prefix_bytes < 1:
        raise ValueError("max-prefix-bytes MUST be positive")
    dsn = _dsn()
    prefixes: dict[str, dict[str, int | str]] = {}
    bounds = _bounds(dsn)
    blocked = False
    for prefix, keep in bounds.items():
        usage = _usage(dsn, prefix, keep)
        planned: dict[str, int | str] = {**usage, "retain": keep}
        planned["would_delete"] = max(0, usage["rows"] - keep)
        if max_prefix_bytes is not None:
            planned["max_prefix_bytes"] = max_prefix_bytes
            if usage["retained_value_storage_bytes"] > max_prefix_bytes:
                planned["blocked"] = "retained_window_exceeds_byte_budget"
                blocked = True
        prefixes[prefix] = planned
    report: dict[str, object] = {
        "mode": "apply" if apply else "dry-run",
        "status": "blocked" if blocked else "ready",
        "prefixes": prefixes,
    }
    if blocked:
        return report
    if not apply:
        report["heimdall_checkpoint"] = await _heimdall_checkpoint(dsn, apply=False)
        return report
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    try:
        for prefix, keep in bounds.items():
            rows = int(prefixes[prefix]["rows"])
            removed = (
                await store.delete_states_beyond(
                    prefix,
                    retain_newest=keep,
                    field=(_LOCAL_WINDOWS.get(prefix, (0, None))[1] or (None, None))[0],
                    value=(_LOCAL_WINDOWS.get(prefix, (0, None))[1] or (None, None))[1],
                )
                if rows > keep
                else 0
            )
            prefixes[prefix]["deleted"] = removed
            remaining = _usage(dsn, prefix, keep)
            prefixes[prefix]["remaining_rows"] = remaining["rows"]
            prefixes[prefix]["remaining_value_storage_bytes"] = remaining["value_storage_bytes"]
            if remaining["rows"] > keep:
                report["status"] = "blocked"
                prefixes[prefix]["blocked"] = "retention_backlog_after_concurrent_writes"
            if max_prefix_bytes is not None and remaining["value_storage_bytes"] > max_prefix_bytes:
                report["status"] = "blocked"
                prefixes[prefix]["blocked"] = "byte_budget_exceeded_after_concurrent_writes"
    finally:
        await store.aclose()
    report["heimdall_checkpoint"] = await _heimdall_checkpoint(dsn, apply=True)
    if vacuum or vacuum_full:
        with psycopg.connect(
            _dsn(_OWNER_DSN_ENV),
            autocommit=True,
            connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            options=_CONNECTION_OPTIONS,
        ) as connection:
            connection.execute(
                "VACUUM (FULL, ANALYZE) state_kv" if vacuum_full else "VACUUM (ANALYZE) state_kv"
            )
        report["vacuumed"] = "state_kv"
        report["vacuum_mode"] = "full" if vacuum_full else "ordinary"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="delete rows past each bound")
    vacuum = parser.add_mutually_exclusive_group()
    vacuum.add_argument("--vacuum", action="store_true", help="with --apply, run ordinary vacuum")
    vacuum.add_argument(
        "--vacuum-full", action="store_true", help="with --apply, explicitly rewrite state_kv"
    )
    parser.add_argument(
        "--max-prefix-bytes",
        type=int,
        help="block if a required retained window exceeds this budget",
    )
    args = parser.parse_args()
    if (args.vacuum or args.vacuum_full) and not args.apply:
        parser.error("vacuum requires --apply")
    if args.max_prefix_bytes is not None and args.max_prefix_bytes < 1:
        parser.error("--max-prefix-bytes MUST be positive")
    report = asyncio.run(
        _run(
            apply=args.apply,
            vacuum=args.vacuum,
            vacuum_full=args.vacuum_full,
            max_prefix_bytes=args.max_prefix_bytes,
        )
    )
    print(json.dumps(report, sort_keys=True))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())
