"""Fail-closed dispatcher for five independently runnable migration branches."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from service_migrations.inventory import load_legacy_inventory
from service_migrations.ownership import SERVICE_IDS, load_ownership_manifest
from service_migrations.schema import fingerprint_owned_schema, load_schema_contract
from service_migrations.validation import validate_service_branches

MIGRATION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MIGRATION_ROOT.parent


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", help="service id or 'all' for validate")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    subparsers.add_parser("heads")
    subparsers.add_parser("history")
    subparsers.add_parser("current")
    stamp = subparsers.add_parser("stamp-baseline")
    stamp.add_argument("--evidence", type=Path, required=True)
    upgrade = subparsers.add_parser("upgrade")
    upgrade.add_argument("revision", nargs="?", default="head")
    upgrade.add_argument("--sql", action="store_true")
    downgrade = subparsers.add_parser("downgrade")
    downgrade.add_argument("revision")
    downgrade.add_argument("--rollback-reference", type=Path, required=True)
    downgrade.add_argument("--evidence-output", type=Path, required=True)
    return parser


def _database_url() -> str:
    database_url = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("FDAI_DATABASE_URL is required")
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url[len("postgresql://") :]
    if not database_url.startswith("postgresql+psycopg://"):
        raise RuntimeError("FDAI_DATABASE_URL must be a PostgreSQL URL")
    return database_url


def _read_versions(table_name: str) -> tuple[str, ...] | None:
    if not table_name.replace("_", "").isalnum():
        raise RuntimeError(f"unsafe version table identifier: {table_name}")
    engine = create_engine(_database_url())
    with engine.connect() as connection:
        exists = connection.execute(
            text("SELECT to_regclass(:name)"),
            {"name": table_name},
        ).scalar()
        if exists is None:
            return None
        rows = connection.execute(text(f"SELECT version_num FROM {table_name}"))  # noqa: S608
        return tuple(sorted(str(row[0]) for row in rows))


def _validate_evidence(
    path: Path,
    *,
    service_id: str,
    head: str,
    count: int,
    expected_schema_fingerprint: str,
) -> str:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("adoption evidence must be a JSON object")
    expected = {
        "service_id": service_id,
        "observed_legacy_head": head,
        "observed_legacy_revision_count": count,
    }
    for key, value in expected.items():
        if raw.get(key) != value:
            raise RuntimeError(f"adoption evidence {key} must be {value!r}")
    for key in ("verified_at", "rollback_reference", "schema_reference"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"adoption evidence {key} is required")
    try:
        verified_at = datetime.fromisoformat(str(raw["verified_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("adoption evidence verified_at must be RFC3339") from exc
    if verified_at.tzinfo is None:
        raise RuntimeError("adoption evidence verified_at must include a timezone")
    if raw.get("observed_schema_fingerprint") != expected_schema_fingerprint:
        raise RuntimeError("adoption evidence schema fingerprint does not match the contract")
    schema_reference = Path(cast(str, raw["schema_reference"]))
    if not schema_reference.is_absolute():
        schema_reference = path.parent / schema_reference
    if not schema_reference.resolve().is_file():
        raise RuntimeError("adoption evidence schema_reference is not resolvable")
    return cast(str, raw["rollback_reference"])


def _live_schema_fingerprint(service_id: str, owned_tables: tuple[str, ...]) -> str:
    engine = create_engine(_database_url())
    with engine.connect() as connection:
        return fingerprint_owned_schema(connection, owned_tables=owned_tables).digest


def main(argv: list[str] | None = None) -> int:
    """Validate ownership, then dispatch one bounded Alembic command."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.service == "all" and args.command != "validate":
        parser.error("service 'all' is valid only with validate")
    if args.service != "all" and args.service not in SERVICE_IDS:
        parser.error(f"unknown service {args.service!r}; expected one of {', '.join(SERVICE_IDS)}")

    inventory = load_legacy_inventory(REPO_ROOT / "alembic" / "versions")
    ownership = load_ownership_manifest(MIGRATION_ROOT / "ownership.json", inventory)
    adoptions = validate_service_branches(MIGRATION_ROOT, inventory, ownership)
    schema_contract = load_schema_contract(MIGRATION_ROOT / "legacy-schema-contract.json")
    if set(schema_contract) != set(SERVICE_IDS):
        raise RuntimeError("legacy schema contract must contain exactly five services")
    if args.command == "validate":
        selected = len(SERVICE_IDS) if args.service == "all" else 1
        print(
            f"validated {selected} service migration branch(es), "
            f"{len(ownership.table_migrators)} tables, {len(ownership.transitions)} transitions"
        )
        return 0

    service_id = cast(str, args.service)
    adoption = adoptions[service_id]
    config = Config(str(MIGRATION_ROOT / "configs" / f"{service_id}.ini"))
    if args.command == "heads":
        command.heads(config)
    elif args.command == "history":
        command.history(config)
    elif args.command == "current":
        command.current(config)
    elif args.command == "stamp-baseline":
        expected_schema = schema_contract[service_id].digest
        _validate_evidence(
            args.evidence,
            service_id=service_id,
            head=adoption.required_legacy_head,
            count=adoption.legacy_revision_count,
            expected_schema_fingerprint=expected_schema,
        )
        legacy_versions = _read_versions(adoption.legacy_version_table)
        if legacy_versions != (adoption.required_legacy_head,):
            raise RuntimeError(
                f"legacy database must be at {adoption.required_legacy_head}; "
                f"observed {legacy_versions}"
            )
        service_versions = _read_versions(adoption.service_version_table)
        if service_versions is not None:
            raise RuntimeError(
                f"{service_id} version table already exists with {service_versions}; "
                "refusing to overwrite service migration history"
            )
        legacy_owned_tables = tuple(
            table
            for table, owner in ownership.table_migrators.items()
            if owner == service_id and table in inventory.table_sources
        )
        live_schema = _live_schema_fingerprint(service_id, legacy_owned_tables)
        if live_schema != expected_schema:
            raise RuntimeError(f"{service_id} schema fingerprint mismatch; refusing baseline stamp")
        command.stamp(config, adoption.baseline_revision)
        resulting_versions = _read_versions(adoption.service_version_table)
        if resulting_versions != (adoption.baseline_revision,):
            raise RuntimeError(
                f"{service_id} baseline stamp did not produce the exact expected head"
            )
    elif args.command == "upgrade":
        if not args.sql:
            service_versions = _read_versions(adoption.service_version_table)
            if service_versions is None or adoption.baseline_revision not in service_versions:
                raise RuntimeError(
                    f"{service_id} baseline is not stamped; run stamp-baseline first"
                )
        command.upgrade(config, args.revision, sql=args.sql)
    elif args.command == "downgrade":
        rollback_reference = args.rollback_reference.resolve()
        if not rollback_reference.is_file():
            raise RuntimeError("--rollback-reference must resolve to a persisted file")
        if args.revision != adoption.baseline_revision:
            raise RuntimeError(
                f"{service_id} rollback target must be exact baseline {adoption.baseline_revision}"
            )
        service_versions = _read_versions(adoption.service_version_table)
        if service_versions is None:
            raise RuntimeError(f"{service_id} baseline has not been adopted")
        branch_head = tuple(ScriptDirectory.from_config(config).get_heads())
        if service_versions != branch_head:
            raise RuntimeError(
                f"{service_id} rollback must start at exact branch head {branch_head}; "
                f"observed {service_versions}"
            )
        command.downgrade(config, args.revision)
        resulting_versions = _read_versions(adoption.service_version_table)
        if resulting_versions != (adoption.baseline_revision,):
            raise RuntimeError(
                f"{service_id} rollback did not produce exact head "
                f"{adoption.baseline_revision}; observed {resulting_versions}"
            )
        legacy_owned_tables = tuple(
            table
            for table, owner in ownership.table_migrators.items()
            if owner == service_id and table in inventory.table_sources
        )
        observed_schema = _live_schema_fingerprint(service_id, legacy_owned_tables)
        expected_schema = schema_contract[service_id].digest
        if observed_schema != expected_schema:
            raise RuntimeError(f"{service_id} rollback schema fingerprint mismatch")
        evidence = {
            "schema_version": 1,
            "service_id": service_id,
            "from_head": branch_head[0],
            "resulting_head": adoption.baseline_revision,
            "schema_fingerprint": observed_schema,
            "completed_at": datetime.now(tz=UTC).isoformat(),
            "persisted_reference": str(rollback_reference),
        }
        _validate_rollback_evidence(
            evidence,
            service_id=service_id,
            from_head=branch_head[0],
            resulting_head=adoption.baseline_revision,
            schema_fingerprint=expected_schema,
        )
        _write_json_atomic(args.evidence_output, evidence)
    else:  # pragma: no cover - argparse constrains commands
        raise AssertionError(args.command)
    return 0


def _write_json_atomic(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _validate_rollback_evidence(
    evidence: dict[str, object],
    *,
    service_id: str,
    from_head: str,
    resulting_head: str,
    schema_fingerprint: str,
) -> None:
    expected = {
        "schema_version": 1,
        "service_id": service_id,
        "from_head": from_head,
        "resulting_head": resulting_head,
        "schema_fingerprint": schema_fingerprint,
    }
    for key, value in expected.items():
        if evidence.get(key) != value:
            raise RuntimeError(f"rollback evidence {key} must be {value!r}")
    completed_at = evidence.get("completed_at")
    if not isinstance(completed_at, str):
        raise RuntimeError("rollback evidence completed_at is required")
    try:
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("rollback evidence completed_at must be RFC3339") from exc
    if completed.tzinfo is None:
        raise RuntimeError("rollback evidence completed_at must include a timezone")
    reference = evidence.get("persisted_reference")
    if not isinstance(reference, str) or not Path(reference).resolve().is_file():
        raise RuntimeError("rollback evidence persisted_reference is not resolvable")
