"""Canonical PostgreSQL schema fingerprints for service baseline adoption."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, bindparam, text


@dataclass(frozen=True)
class SchemaFingerprint:
    """Content digest and bounded catalog counts for one service schema."""

    digest: str
    table_count: int
    column_count: int
    constraint_count: int
    extensions: tuple[str, ...]


def load_schema_contract(path: Path) -> dict[str, SchemaFingerprint]:
    """Load exact checked-in fingerprint expectations for all services."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    services = raw.get("services") if isinstance(raw, dict) else None
    if raw.get("schema_version") != 1 or not isinstance(services, dict):
        raise ValueError("legacy schema contract must declare version 1 services")
    contract: dict[str, SchemaFingerprint] = {}
    for service_id, value in services.items():
        if not isinstance(service_id, str) or not isinstance(value, dict):
            raise ValueError("legacy schema contract entries must be objects")
        extensions = value.get("extensions")
        if not isinstance(extensions, list) or not all(
            isinstance(item, str) and item for item in extensions
        ):
            raise ValueError(f"{service_id}: schema contract extensions are invalid")
        try:
            fingerprint = SchemaFingerprint(
                digest=str(value["digest"]),
                table_count=int(value["table_count"]),
                column_count=int(value["column_count"]),
                constraint_count=int(value["constraint_count"]),
                extensions=tuple(extensions),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{service_id}: schema contract is incomplete") from exc
        if not fingerprint.digest.startswith("sha256:") or len(fingerprint.digest) != 71:
            raise ValueError(f"{service_id}: schema contract digest is invalid")
        contract[service_id] = fingerprint
    return contract


def fingerprint_owned_schema(
    connection: Connection,
    *,
    owned_tables: Iterable[str],
) -> SchemaFingerprint:
    """Fingerprint exact owned tables, columns, constraints, and extensions."""
    tables = tuple(sorted(set(owned_tables)))
    if not tables:
        raise ValueError("schema fingerprint requires at least one owned table")
    invalid = tuple(table for table in tables if not table.replace("_", "").isalnum())
    if invalid:
        raise ValueError(f"schema fingerprint contains unsafe table names: {invalid}")

    columns = (
        connection.execute(
            text(
                "SELECT table_name, ordinal_position, column_name, data_type, udt_name, "
                "is_nullable, COALESCE(column_default, '') AS column_default "
                "FROM information_schema.columns WHERE table_schema = current_schema() "
                "AND table_name IN :tables ORDER BY table_name, ordinal_position"
            ).bindparams(bindparam("tables", expanding=True)),
            {"tables": tables},
        )
        .mappings()
        .all()
    )
    constraints = (
        connection.execute(
            text(
                "SELECT t.relname AS table_name, c.conname AS constraint_name, "
                "c.contype AS constraint_type, pg_get_constraintdef(c.oid, true) AS definition "
                "FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = current_schema() AND t.relname IN :tables "
                "ORDER BY t.relname, c.conname"
            ).bindparams(bindparam("tables", expanding=True)),
            {"tables": tables},
        )
        .mappings()
        .all()
    )
    extensions = (
        connection.execute(text("SELECT extname FROM pg_extension ORDER BY extname"))
        .mappings()
        .all()
    )
    observed_tables = {str(row["table_name"]) for row in columns}
    missing = sorted(set(tables) - observed_tables)
    if missing:
        raise RuntimeError(f"owned schema tables are missing: {missing}")
    payload: dict[str, Any] = {
        "tables": list(tables),
        "columns": [dict(row) for row in columns],
        "constraints": [dict(row) for row in constraints],
        "extensions": [dict(row) for row in extensions],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return SchemaFingerprint(
        digest="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        table_count=len(tables),
        column_count=len(columns),
        constraint_count=len(constraints),
        extensions=tuple(str(row["extname"]) for row in extensions),
    )


__all__ = ["SchemaFingerprint", "fingerprint_owned_schema", "load_schema_contract"]
