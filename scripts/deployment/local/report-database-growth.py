#!/usr/bin/env python3
"""Report local database size, the largest tables, and growth since the previous report.

Read-only. Only loopback port 5432 database ``fdai`` is accepted, and no connection value is
printed. A warning appears before the 2 GiB recreation guard so growth is visible while it is
still cheap to fix.
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
from psycopg.conninfo import conninfo_to_dict

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_DSN_ENV = "FDAI_STATE_STORE_DSN"
_BOUND_ENV = "FDAI_LOCAL_DATABASE_RECREATE_MAX_BYTES"
_DEFAULT_BOUND = 2 * 1024 * 1024 * 1024
WARN_FRACTION = 0.75
_SAMPLE_PATH = Path(".fdai/local-db-growth.json")
_MIB = 1024 * 1024


def assess(size_bytes: int, bound_bytes: int) -> str:
    """Return ``ok``, ``warn`` before the guard, or ``over`` at or past it."""
    if size_bytes >= bound_bytes:
        return "over"
    return "warn" if size_bytes >= bound_bytes * WARN_FRACTION else "ok"


def growth_per_hour(previous: dict[str, Any] | None, size_bytes: int, now: float) -> float | None:
    """Return bytes per hour since the previous sample, or ``None`` without a usable one."""
    if not previous:
        return None
    elapsed = now - float(previous.get("at", now))
    if elapsed < 60:
        return None
    return (size_bytes - int(previous.get("size_bytes", size_bytes))) / elapsed * 3600


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


def _bound() -> int:
    raw = os.environ.get(_BOUND_ENV, "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else _DEFAULT_BOUND


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=5, help="number of largest tables to list")
    parser.add_argument("--no-sample", action="store_true", help="do not record this size sample")
    args = parser.parse_args()
    with psycopg.connect(_dsn(), connect_timeout=5) as connection:
        connection.execute("SET default_transaction_read_only = on")
        size = int(connection.execute("SELECT pg_database_size(current_database())").fetchone()[0])  # type: ignore[index]
        tables = connection.execute(
            "SELECT c.relname, pg_total_relation_size(c.oid) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind='r' "
            "ORDER BY pg_total_relation_size(c.oid) DESC LIMIT %s",
            (max(1, min(args.top, 20)),),
        ).fetchall()
    bound = _bound()
    now = time.time()
    previous: dict[str, Any] | None = None
    if _SAMPLE_PATH.is_file():
        try:
            previous = json.loads(_SAMPLE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = None
    rate = growth_per_hour(previous, size, now)
    status = assess(size, bound)
    print(f"size:   {size / _MIB:,.0f} MiB of {bound / _MIB:,.0f} MiB ({size / bound:.0%})")
    if rate is not None:
        print(f"growth: {rate / _MIB:+,.1f} MiB/hour since the previous report")
    for name, table_size in tables:
        print(f"  {name:<46} {table_size / _MIB:>8,.0f} MiB")
    if status != "ok":
        print(
            f"WARNING: database is {status} the recreation guard; run "
            "scripts/deployment/local/compact-local-database.py to apply retention"
        )
    if not args.no_sample:
        _SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SAMPLE_PATH.write_text(json.dumps({"at": now, "size_bytes": size}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
