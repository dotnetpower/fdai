#!/usr/bin/env python3
"""Apply the state retention bounds to the loopback development database.

The default run only reports how many rows each bound would remove. ``--apply`` deletes the
oldest rows past each bound, using the same newest-N windows the running services use, and
``--vacuum`` tunes local vacuum thresholds and rewrites ``state_kv`` to return the space.
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

import psycopg
from fdai.agents import (
    BASELINE_EVALUATION_COMPLETION_PREFIX,
    BASELINE_EVALUATION_MIN_RETENTION,
    BASELINE_EVALUATION_OUTCOME_PREFIX,
    NO_RULE_FOLD_PREFIX,
    NO_RULE_FOLD_RETENTION,
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


def _count(dsn: str, prefix: str) -> int:
    with psycopg.connect(
        dsn, connect_timeout=_CONNECT_TIMEOUT_SECONDS, options=_CONNECTION_OPTIONS
    ) as connection:
        connection.execute("SET default_transaction_read_only = on")
        row = connection.execute(
            "SELECT count(*) FROM state_kv WHERE key LIKE %s", (prefix.replace("%", r"\%") + "%",)
        ).fetchone()
    return int(row[0]) if row else 0


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
    }


async def _run(*, apply: bool, vacuum: bool) -> dict[str, object]:
    dsn = _dsn()
    prefixes: dict[str, dict[str, int]] = {}
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    try:
        for prefix, keep in _bounds(dsn).items():
            rows = _count(dsn, prefix)
            removed = (
                await store.delete_states_beyond(prefix, retain_newest=keep)
                if apply and rows > keep
                else max(0, rows - keep)
            )
            prefixes[prefix] = {
                "rows": rows,
                "retain": keep,
                "deleted" if apply else "would_delete": removed,
            }
    finally:
        await store.aclose()
    report: dict[str, object] = {"mode": "apply" if apply else "dry-run", "prefixes": prefixes}
    if apply and vacuum:
        # Only the table owner may rewrite state_kv; the runtime role cannot.
        with psycopg.connect(
            _dsn(_OWNER_DSN_ENV),
            autocommit=True,
            connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            options=_CONNECTION_OPTIONS,
        ) as connection:
            connection.execute(
                "ALTER TABLE state_kv SET (autovacuum_vacuum_scale_factor=0.01, "
                "autovacuum_vacuum_threshold=1000, toast.autovacuum_vacuum_scale_factor=0.01, "
                "toast.autovacuum_vacuum_threshold=1000)"
            )
            connection.execute("VACUUM (FULL, ANALYZE) state_kv")
        report["vacuumed"] = "state_kv"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="delete rows past each bound")
    parser.add_argument(
        "--vacuum", action="store_true", help="with --apply, rewrite state_kv afterwards"
    )
    args = parser.parse_args()
    if args.vacuum and not args.apply:
        parser.error("--vacuum requires --apply")
    print(json.dumps(asyncio.run(_run(apply=args.apply, vacuum=args.vacuum)), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
