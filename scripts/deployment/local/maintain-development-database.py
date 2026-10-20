#!/usr/bin/env python3
"""Check loopback database bounds and require explicit permission for recreation."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

_DEFAULT_MAX_BYTES = 1024 * 1024 * 1024
_MIN_MAX_BYTES = 64 * 1024 * 1024
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_PRESERVED_STATE_VERSION = "1.0.0"
_PRESERVED_REPOSITORY_PREFIX = "runtime:code-security-repository:"
_MAX_PRESERVED_REPOSITORIES = 200
_MAX_PRESERVED_STATE_BYTES = 1024 * 1024


class _PreservedRegistration(TypedDict):
    key: str
    value: dict[str, object]


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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="return nonzero when the database exceeds its recreation threshold",
    )
    mode.add_argument(
        "--restore-preserved-state",
        type=Path,
        help="restore private durable local state after migrations complete",
    )
    mode.add_argument(
        "--allow-recreate",
        action="store_true",
        help="explicitly discard the disposable local database generation when over its bound",
    )
    parser.add_argument(
        "--recreated-marker",
        type=Path,
        help="retain a private marker until matching local broker state is reset",
    )
    parser.add_argument(
        "--preserved-state",
        type=Path,
        help="write private durable local state before recreating the database",
    )
    return parser


def _write_recreated_marker(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("database_recreated\n", encoding="ascii")
    path.chmod(0o600)


def _preserved_registrations(target: LocalDatabaseTarget) -> list[_PreservedRegistration]:
    with psycopg.connect(make_conninfo(**target.connection_info)) as connection:
        rows = connection.execute(
            """
            SELECT key, value
              FROM state_kv
             WHERE key LIKE %s
             ORDER BY key
             LIMIT %s
            """,
            (_PRESERVED_REPOSITORY_PREFIX + "%", _MAX_PRESERVED_REPOSITORIES + 1),
        ).fetchall()
    if len(rows) > _MAX_PRESERVED_REPOSITORIES:
        raise RuntimeError("code-security repository preservation exceeds its row bound")
    registrations: list[_PreservedRegistration] = []
    for key, value in rows:
        if (
            not isinstance(key, str)
            or not key.startswith(_PRESERVED_REPOSITORY_PREFIX)
            or not isinstance(value, dict)
        ):
            raise RuntimeError("code-security repository preservation found malformed state")
        registrations.append({"key": key, "value": value})
    return registrations


def _write_preserved_state(path: Path, registrations: list[_PreservedRegistration]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {
        "schema_version": _PRESERVED_STATE_VERSION,
        "code_security_repositories": registrations,
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(encoded) > _MAX_PRESERVED_STATE_BYTES:
        raise RuntimeError("preserved local state exceeds its byte bound")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_preserved_state(path: Path) -> list[_PreservedRegistration]:
    if path.is_symlink():
        raise ValueError("preserved local state MUST NOT be a symlink")
    stat = path.stat()
    if stat.st_mode & 0o077:
        raise ValueError("preserved local state MUST NOT be group- or world-readable")
    if stat.st_size > _MAX_PRESERVED_STATE_BYTES:
        raise ValueError("preserved local state exceeds its byte bound")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "code_security_repositories",
    }:
        raise ValueError("preserved local state has an invalid envelope")
    if payload["schema_version"] != _PRESERVED_STATE_VERSION:
        raise ValueError("preserved local state has an unsupported schema version")
    registrations = payload["code_security_repositories"]
    if not isinstance(registrations, list) or len(registrations) > _MAX_PRESERVED_REPOSITORIES:
        raise ValueError("preserved local state has an invalid repository collection")
    validated: list[_PreservedRegistration] = []
    for item in registrations:
        if (
            not isinstance(item, dict)
            or set(item) != {"key", "value"}
            or not isinstance(item["key"], str)
            or not item["key"].startswith(_PRESERVED_REPOSITORY_PREFIX)
            or not isinstance(item["value"], dict)
        ):
            raise ValueError("preserved local state has a malformed repository")
        validated.append({"key": item["key"], "value": item["value"]})
    return validated


async def _restore_preserved_state(target: LocalDatabaseTarget, preserved_state: Path) -> int:
    repo_root = Path(__file__).resolve().parents[3]
    sys.path[:0] = [
        str(repo_root / "services/core-control-plane/src"),
        str(repo_root / "packages/service-contracts/src"),
        str(repo_root / "packages/github-app-auth/src"),
    ]
    from fdai.delivery.persistence.postgres import (  # noqa: PLC0415
        PostgresStateStore,
        PostgresStateStoreConfig,
    )
    from fdai.delivery.persistence.state_store_code_security_repository import (  # noqa: PLC0415
        parse_repository,
        repository_state_key,
    )

    registrations = _read_preserved_state(preserved_state)
    store = PostgresStateStore(
        config=PostgresStateStoreConfig(dsn=make_conninfo(**target.connection_info))
    )
    restored = 0
    try:
        for item in registrations:
            record = dict(item["value"])
            repository = parse_repository(record)
            key = repository_state_key(repository.repository_alias)
            if item["key"] != key:
                raise ValueError("preserved repository key does not match its record")
            current = await store.read_state(key)
            if current is not None:
                if dict(current) != record:
                    raise RuntimeError("preserved repository conflicts with current local state")
                continue
            audit = {
                "kind": "code_security_repository_restored",
                "producer_principal": "Heimdall",
                "change": "restored_after_local_database_recreation",
                "repository_alias": repository.repository_alias,
                "provider": repository.provider,
                "enabled": repository.enabled,
                "registration_revision": repository.revision,
                "actor": repository.registered_by,
                "execution_authority": False,
            }
            if not await store.write_state_with_audit_if_absent(key, record, audit):
                current = await store.read_state(key)
                if current is None or dict(current) != record:
                    raise RuntimeError("preserved repository restore changed concurrently")
                continue
            restored += 1
    finally:
        await store.aclose()
    return restored


def main() -> int:
    args = _parser().parse_args()
    target = _target(os.environ.get("FDAI_DATABASE_URL", ""))
    if args.restore_preserved_state is not None:
        restored = asyncio.run(_restore_preserved_state(target, args.restore_preserved_state))
        print(f"restored {restored} code-security repositories after database recreation")
        return 0
    if (args.recreated_marker is None) != (args.preserved_state is None):
        raise ValueError("--recreated-marker and --preserved-state MUST be supplied together")
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
        if not args.allow_recreate:
            print(
                f"local database exceeds its size bound: {current} > {maximum}; "
                "automatic recreation refused and existing data preserved. "
                "Review backup and history requirements before explicitly running "
                "prepare-console-state.sh --allow-recreate.",
                file=sys.stderr,
            )
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
        if args.preserved_state is not None:
            _write_preserved_state(
                args.preserved_state,
                _preserved_registrations(target),
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
