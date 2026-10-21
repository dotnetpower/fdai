"""Bounded, read-only recovery observations using the Hub's runtime database identity."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Literal

from azure.core.exceptions import AzureError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, Table, Text, func, inspect, literal, select, text
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.exc import MultipleResultsFound, SQLAlchemyError

from fdai_lifecycle_hub.migrations import _prepared_revision, _versions, require_schema
from fdai_lifecycle_hub.remote import remote_engine

ROW_LIMIT = 1000
SAMPLE_LIMIT = 32
RECEIPT_LIMIT = 128 * 1024
Kind = Literal["release", "target"]
Target = Literal["source", "restored"]


class InspectionError(ValueError):
    """A sanitized observation or comparison failure."""


class TableObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    rows: int = Field(ge=0, le=ROW_LIMIT)
    sample_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    columns_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    format: Literal["fdai.hub-db-inspection.v1"] = "fdai.hub-db-inspection.v1"
    kind: Kind
    target: Target
    revision: Literal[1, 2] = 1
    database_binding: str = Field(pattern=r"^[0-9a-f]{64}$")
    host_binding: str = Field(pattern=r"^[0-9a-f]{64}$")
    tables: dict[str, TableObservation]


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _require_endpoint_binding(url: URL) -> None:
    if {"host", "hostaddr", "port", "dbname", "user", "service"} & url.query.keys():
        raise InspectionError("database_routing_override_not_allowed")


def _tables(kind: Kind, connection: Connection | None = None) -> list[Table]:
    if kind == "release":
        from fdai_release_hub.database import metadata

        tables = list(metadata.sorted_tables)
    else:
        from fdai_lifecycle_hub.models import Base
        from fdai_lifecycle_hub.remote_catalog import metadata

        tables = [*Base.metadata.sorted_tables, *metadata.sorted_tables]
    namespace = "release_hub" if kind == "release" else "lifecycle_hub"
    versions = _versions(namespace)
    if connection is not None:
        _prepared_revision(connection, versions)
    return sorted([*tables, versions], key=lambda table: table.name)


def _observe_table(connection: Connection, table: Table) -> TableObservation:
    inspector = inspect(connection)
    columns = inspector.get_columns(table.name)
    expected = {column.name for column in table.columns}
    if {column["name"] for column in columns} != expected:
        raise InspectionError("schema_columns_mismatch")
    for column in columns:
        model = table.c[column["name"]]
        if column["nullable"] != model.nullable or column["type"].compile(
            dialect=connection.dialect
        ) != model.type.compile(dialect=connection.dialect):
            raise InspectionError("schema_column_type_mismatch")
    primary = [column.name for column in table.primary_key]
    if not primary or inspector.get_pk_constraint(table.name)["constrained_columns"] != primary:
        raise InspectionError("schema_primary_key_mismatch")
    privileges = connection.execute(
        text(
            "SELECT has_database_privilege(current_database(), 'CONNECT'), "
            "has_schema_privilege(current_schema(), 'USAGE'), "
            "has_schema_privilege(current_schema(), 'CREATE'), "
            "has_table_privilege(:table, 'SELECT'), has_table_privilege(:table, 'INSERT'), "
            "has_table_privilege(:table, 'UPDATE'), has_table_privilege(:table, 'DELETE')"
        ),
        {"table": table.name},
    ).one()
    if not all(privileges):
        raise InspectionError("runtime_privileges_missing")
    for primary_name in primary:
        sequence = connection.scalar(
            text("SELECT pg_get_serial_sequence(:table, :column)"),
            {"table": table.name, "column": primary_name},
        )
        if sequence and not connection.scalar(
            text("SELECT has_sequence_privilege(:sequence, 'USAGE')"), {"sequence": sequence}
        ):
            raise InspectionError("runtime_sequence_privileges_missing")
    limited = select(literal(1)).select_from(table).limit(ROW_LIMIT + 1).subquery()
    count = connection.scalar(select(func.count()).select_from(limited))
    if count is None or count > ROW_LIMIT:
        raise InspectionError("table_row_bound_exceeded")
    rows = select(table).order_by(*table.primary_key).limit(SAMPLE_LIMIT).subquery()
    fingerprints = select(
        func.encode(
            func.sha256(func.convert_to(func.row_to_json(rows.table_valued()).cast(Text), "UTF8")),
            "hex",
        ).label("fingerprint")
    ).subquery()
    aggregate = func.string_agg(
        fingerprints.c.fingerprint,
        aggregate_order_by(literal(""), fingerprints.c.fingerprint),
    )
    sample = connection.scalar(
        select(
            func.encode(func.sha256(func.convert_to(func.coalesce(aggregate, ""), "UTF8")), "hex")
        )
    )
    if not isinstance(sample, str):
        raise InspectionError("sample_fingerprint_unavailable")
    signature = [
        (column["name"], str(column["type"]), column["nullable"], column.get("default"))
        for column in columns
    ]
    return TableObservation(rows=count, sample_sha256=sample, columns_sha256=_digest(signature))


def observe(engine: Engine, kind: Kind, target: Target, baseline: Receipt | None = None) -> Receipt:
    """Observe one repeatable-read snapshot, always rolling back before returning."""
    _require_endpoint_binding(engine.url)
    if engine.dialect.name != "postgresql":
        raise InspectionError("postgresql_required")
    if (target == "restored") != (baseline is not None):
        raise InspectionError("source_baseline_required_only_for_restored")
    phase = "connect"
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(text("SET LOCAL statement_timeout = '5s'"))
                connection.execute(text("SET LOCAL lock_timeout = '2s'"))
                connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
                phase = "schema"
                namespace = "release_hub" if kind == "release" else "lifecycle_hub"
                require_schema(connection, namespace)
                binding = connection.execute(text("SELECT current_database(), current_user")).one()
                tables = {}
                for table in _tables(kind, connection):
                    phase = f"table_{table.name}"
                    tables[table.name] = _observe_table(connection, table)
                if tables[f"{namespace}_schema_revision"].rows != 1:
                    raise InspectionError("schema_revision_row_count_mismatch")
                result = Receipt(
                    kind=kind,
                    target=target,
                    revision=2 if kind == "target" else 1,
                    database_binding=_digest(list(binding)),
                    host_binding=_digest(engine.url.host),
                    tables=tables,
                )
                if baseline is not None:
                    if baseline.target != "source" or baseline.kind != kind:
                        raise InspectionError("baseline_target_mismatch")
                    if baseline.host_binding == result.host_binding:
                        raise InspectionError("restored_host_must_differ")
                    if baseline.database_binding != result.database_binding:
                        raise InspectionError("database_or_principal_mismatch")
                    if baseline.tables != result.tables:
                        raise InspectionError("restored_state_mismatch")
                return result
            finally:
                transaction.rollback()
    except MultipleResultsFound:
        raise InspectionError(f"schema_revision_row_count_mismatch stage={phase}") from None
    except SQLAlchemyError as error:
        state = getattr(error.orig, "sqlstate", None) if hasattr(error, "orig") else None
        code = (
            state if isinstance(state, str) and len(state) == 5 and state.isalnum() else "unknown"
        )
        raise InspectionError(f"database_{phase}_failed stage={phase} sqlstate={code}") from None
    except ValueError as error:
        reason = str(error) if isinstance(error, InspectionError) else "schema_revision_mismatch"
        raise InspectionError(f"{reason} stage={phase}") from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=["release", "target"])
    parser.add_argument("--target", required=True, choices=["source", "restored"])
    parser.add_argument("--restored-host")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    engine = None
    step = "configuration"
    try:
        if (args.target == "restored") != bool(args.restored_host and args.baseline):
            raise InspectionError("restored_requires_host_and_source_baseline")
        if args.target == "source" and (args.restored_host or args.baseline):
            raise InspectionError("source_rejects_restore_inputs")
        baseline = None
        if args.baseline:
            step = "baseline"
            with args.baseline.open("rb") as stream:
                data = stream.read(RECEIPT_LIMIT + 1)
            if len(data) > RECEIPT_LIMIT:
                raise InspectionError("baseline_too_large")
            baseline = Receipt.model_validate_json(data)
        step = "configuration"
        variable = (
            "FDAI_RELEASE_HUB_DATABASE_URL"
            if args.kind == "release"
            else "FDAI_LIFECYCLE_HUB_DATABASE_URL"
        )
        original = os.environ.get(variable)
        if original:
            _require_endpoint_binding(make_url(original))
        if args.restored_host:
            if not original:
                raise InspectionError("database_configuration_missing")
            url = make_url(original)
            host = args.restored_host
            if not host or any(
                char not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for char in host
            ):
                raise InspectionError("invalid_restored_host")
            if host == url.host:
                raise InspectionError("restored_host_must_differ")
            os.environ[variable] = url.set(host=host).render_as_string(hide_password=False)
        try:
            engine = remote_engine(args.kind)
        finally:
            if original is not None:
                os.environ[variable] = original
            else:
                os.environ.pop(variable, None)
        step = "observation"
        receipt = observe(engine, args.kind, args.target, baseline)
        step = "receipt"
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(receipt.model_dump_json() + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            args.output.unlink()
            raise
        print(f"hub_database_inspection_ok target={args.target} tables={len(receipt.tables)}")
    except (InspectionError, OSError, ValueError, AzureError, SQLAlchemyError):
        # Configuration and driver messages can contain connection strings or row values.
        error = sys.exception()
        reason = (
            str(error) if isinstance(error, InspectionError) else "configuration_or_receipt_invalid"
        )
        if isinstance(error, AzureError):
            reason = "database_credential_unavailable"
        print(f"hub_database_inspection_failed step={step} reason={reason}", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
