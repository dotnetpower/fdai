#!/usr/bin/env python3
"""Bound loopback development database growth through whole-database recreation."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

_DEFAULT_MAX_BYTES = 1024 * 1024 * 1024
_MIN_MAX_BYTES = 64 * 1024 * 1024
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


@dataclass(frozen=True, slots=True)
class LocalDatabaseTarget:
    connection_info: dict[str, Any]
    database: str
    owner: str


def _target(database_url: str) -> LocalDatabaseTarget:
    normalized = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    connection_info = conninfo_to_dict(normalized)
    host = str(connection_info.get("host") or "")
    port = str(connection_info.get("port") or "5432")
    database = str(connection_info.get("dbname") or "")
    owner = str(connection_info.get("user") or "")
    if host not in _LOOPBACK_HOSTS or port != "5432" or database != "fdai" or not owner:
        raise ValueError(
            "development database maintenance requires loopback port 5432 and database fdai"
        )
    return LocalDatabaseTarget(connection_info, database, owner)


def _max_bytes(raw: str | None) -> int:
    if raw is None or not raw.strip():
        return _DEFAULT_MAX_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("FDAI_LOCAL_DATABASE_RECREATE_MAX_BYTES MUST be an integer") from exc
    if value < _MIN_MAX_BYTES:
        raise ValueError(
            f"FDAI_LOCAL_DATABASE_RECREATE_MAX_BYTES MUST be at least {_MIN_MAX_BYTES}"
        )
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="return nonzero when the database exceeds its recreation threshold",
    )
    parser.add_argument(
        "--recreated-marker",
        type=Path,
        help="retain a private marker until matching local broker state is reset",
    )
    return parser


def _write_recreated_marker(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("database_recreated\n", encoding="ascii")
    path.chmod(0o600)


def main() -> int:
    args = _parser().parse_args()
    target = _target(os.environ.get("FDAI_DATABASE_URL", ""))
    maximum = _max_bytes(os.environ.get("FDAI_LOCAL_DATABASE_RECREATE_MAX_BYTES"))
    maintenance_info = {**target.connection_info, "dbname": "postgres"}
    with psycopg.connect(make_conninfo(**maintenance_info), autocommit=True) as connection:
        size = connection.execute("SELECT pg_database_size(%s)", (target.database,)).fetchone()
        current = int(size[0]) if size is not None and size[0] is not None else 0
        if current <= maximum:
            print(f"local database size is within bound: {current} <= {maximum}")
            return 0
        if args.check:
            print(f"local database recreation required: {current} > {maximum}")
            return 3
        active = connection.execute(
            "SELECT COUNT(*) FROM pg_stat_activity WHERE datname=%s",
            (target.database,),
        ).fetchone()
        active_count = int(active[0]) if active is not None else 0
        if active_count:
            raise RuntimeError(
                "local database exceeds its size bound; stop local services before preparation"
            )
        if args.recreated_marker is not None:
            _write_recreated_marker(args.recreated_marker)
        connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(target.database)))
        connection.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(target.database),
                sql.Identifier(target.owner),
            )
        )
    print(f"recreated local development database after size exceeded {maximum} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
