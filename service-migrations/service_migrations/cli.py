"""Fail-closed dispatcher for five independently runnable migration branches."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from service_migrations.adoption import AdoptionManifest
from service_migrations.inventory import load_legacy_inventory
from service_migrations.ownership import (
    SERVICE_IDS,
    OwnershipManifest,
    load_ownership_manifest,
    migration_order,
)
from service_migrations.schema import (
    SchemaFingerprint,
    fingerprint_owned_schema,
    load_schema_contract,
)
from service_migrations.validation import validate_service_branches

MIGRATION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MIGRATION_ROOT.parent


def _lock_key(scope: str) -> int:
    digest = hashlib.sha256(f"fdai-migration:{scope}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


_COORDINATION_LOCK_KEY = _lock_key("all-services")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", help="service id or 'all' for validate")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    subparsers.add_parser("heads")
    subparsers.add_parser("history")
    subparsers.add_parser("current")
    prepare = subparsers.add_parser("prepare-adoption")
    prepare.add_argument("--evidence-output", type=Path, required=True)
    prepare.add_argument("--schema-output", type=Path, required=True)
    prepare.add_argument("--rollback-reference", required=True)
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


@contextmanager
def _coordination_connection() -> Iterator[Connection]:
    """Hold the cross-service migration fence from dependency checks through DDL."""
    engine = create_engine(_database_url())
    with engine.connect() as connection:
        connection.execute(
            text("SELECT pg_advisory_lock(:lock_key)"),
            {"lock_key": _COORDINATION_LOCK_KEY},
        )
        connection.commit()
        try:
            yield connection
        finally:
            if connection.in_transaction():
                connection.rollback()
            connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": _COORDINATION_LOCK_KEY},
            )
            connection.commit()


def _read_versions(
    table_name: str,
    *,
    connection: Connection | None = None,
) -> tuple[str, ...] | None:
    if not table_name.replace("_", "").isalnum():
        raise RuntimeError(f"unsafe version table identifier: {table_name}")
    if connection is not None:
        return _read_versions_on_connection(connection, table_name)
    engine = create_engine(_database_url())
    with engine.connect() as owned_connection:
        return _read_versions_on_connection(owned_connection, table_name)


def _read_versions_on_connection(
    connection: Connection,
    table_name: str,
) -> tuple[str, ...] | None:
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


def _live_schema_fingerprint(
    service_id: str,
    owned_tables: tuple[str, ...],
    *,
    connection: Connection | None = None,
) -> str:
    if connection is not None:
        return fingerprint_owned_schema(connection, owned_tables=owned_tables).digest
    engine = create_engine(_database_url())
    with engine.connect() as owned_connection:
        return fingerprint_owned_schema(owned_connection, owned_tables=owned_tables).digest


def _revision_contains(config: Config, observed: str, required: str) -> bool:
    script = ScriptDirectory.from_config(config)
    return required in {
        revision.revision for revision in script.iterate_revisions(observed, "base")
    }


def _prepare_adoption_evidence(
    service_id: str,
    *,
    adoption: AdoptionManifest,
    expected_schema_fingerprint: str,
    legacy_owned_tables: tuple[str, ...],
    evidence_output: Path,
    schema_output: Path,
    rollback_reference: str,
) -> None:
    if not rollback_reference.strip():
        raise RuntimeError("adoption rollback reference must be non-empty")
    legacy_versions = _read_versions(adoption.legacy_version_table)
    if legacy_versions != (adoption.required_legacy_head,):
        raise RuntimeError(
            f"legacy database must be at {adoption.required_legacy_head}; "
            f"observed {legacy_versions}"
        )
    observed_schema = _live_schema_fingerprint(service_id, legacy_owned_tables)
    if observed_schema != expected_schema_fingerprint:
        raise RuntimeError(f"{service_id} schema fingerprint mismatch; refusing adoption")
    verified_at = datetime.now(tz=UTC).isoformat()
    _write_json_atomic(
        schema_output,
        {
            "schema_version": 1,
            "service_id": service_id,
            "owned_tables": list(legacy_owned_tables),
            "observed_schema_fingerprint": observed_schema,
            "verified_at": verified_at,
        },
    )
    _write_json_atomic(
        evidence_output,
        {
            "service_id": service_id,
            "observed_legacy_head": adoption.required_legacy_head,
            "observed_legacy_revision_count": adoption.legacy_revision_count,
            "observed_schema_fingerprint": observed_schema,
            "verified_at": verified_at,
            "schema_reference": str(schema_output.resolve()),
            "rollback_reference": rollback_reference,
        },
    )


def _stamp_service_baseline(
    service_id: str,
    *,
    adoption: AdoptionManifest,
    expected_schema_fingerprint: str,
    legacy_owned_tables: tuple[str, ...],
    evidence: Path,
) -> None:
    _validate_evidence(
        evidence,
        service_id=service_id,
        head=adoption.required_legacy_head,
        count=adoption.legacy_revision_count,
        expected_schema_fingerprint=expected_schema_fingerprint,
    )
    legacy_versions = _read_versions(adoption.legacy_version_table)
    if legacy_versions != (adoption.required_legacy_head,):
        raise RuntimeError(
            f"legacy database must be at {adoption.required_legacy_head}; "
            f"observed {legacy_versions}"
        )
    service_versions = _read_versions(adoption.service_version_table)
    if service_versions == (adoption.baseline_revision,):
        return
    if service_versions is not None:
        raise RuntimeError(
            f"{service_id} version table already exists with {service_versions}; "
            "refusing to overwrite service migration history"
        )
    live_schema = _live_schema_fingerprint(service_id, legacy_owned_tables)
    if live_schema != expected_schema_fingerprint:
        raise RuntimeError(f"{service_id} schema fingerprint mismatch; refusing baseline stamp")
    config = Config(str(MIGRATION_ROOT / "configs" / f"{service_id}.ini"))
    command.stamp(config, adoption.baseline_revision)
    resulting_versions = _read_versions(adoption.service_version_table)
    if resulting_versions != (adoption.baseline_revision,):
        raise RuntimeError(f"{service_id} baseline stamp did not produce the exact expected head")


def _require_dependency_revisions(
    service_id: str,
    ownership: OwnershipManifest,
    adoptions: dict[str, AdoptionManifest],
    *,
    connection: Connection | None = None,
) -> None:
    for dependency in ownership.migration_dependencies:
        if dependency.consumer_service != service_id:
            continue
        provider = dependency.provider_service
        versions = _read_versions(
            adoptions[provider].service_version_table,
            connection=connection,
        )
        provider_config = Config(str(MIGRATION_ROOT / "configs" / f"{provider}.ini"))
        if (
            versions is None
            or len(versions) != 1
            or not _revision_contains(provider_config, versions[0], dependency.provider_revision)
        ):
            raise RuntimeError(
                f"{service_id} migration requires {provider}:{dependency.provider_revision}; "
                f"observed {versions}"
            )


def _require_dependents_at_baseline(
    service_id: str,
    ownership: OwnershipManifest,
    adoptions: dict[str, AdoptionManifest],
    *,
    connection: Connection | None = None,
) -> None:
    for dependency in ownership.migration_dependencies:
        if dependency.provider_service != service_id:
            continue
        consumer = dependency.consumer_service
        baseline = adoptions[consumer].baseline_revision
        versions = _read_versions(
            adoptions[consumer].service_version_table,
            connection=connection,
        )
        if versions != (baseline,):
            raise RuntimeError(
                f"{service_id} downgrade requires dependent {consumer} at baseline "
                f"{baseline}; observed {versions}"
            )


def _upgrade_service(
    service_id: str,
    *,
    revision: str,
    sql: bool,
    ownership: OwnershipManifest,
    adoptions: dict[str, AdoptionManifest],
) -> None:
    adoption = adoptions[service_id]
    config = Config(str(MIGRATION_ROOT / "configs" / f"{service_id}.ini"))
    if sql:
        command.upgrade(config, revision, sql=True)
        return
    with _coordination_connection() as connection:
        service_versions = _read_versions(
            adoption.service_version_table,
            connection=connection,
        )
        if (
            service_versions is None
            or len(service_versions) != 1
            or not _revision_contains(config, service_versions[0], adoption.baseline_revision)
        ):
            raise RuntimeError(f"{service_id} baseline is not stamped; run stamp-baseline first")
        _require_dependency_revisions(
            service_id,
            ownership,
            adoptions,
            connection=connection,
        )
        connection.commit()
        config.attributes["connection"] = connection
        command.upgrade(config, revision, sql=False)


def _downgrade_service(
    service_id: str,
    *,
    revision: str,
    rollback_reference: Path,
    evidence_output: Path,
    ownership: OwnershipManifest,
    adoptions: dict[str, AdoptionManifest],
    schema_contract: dict[str, SchemaFingerprint],
    legacy_tables: frozenset[str],
) -> None:
    adoption = adoptions[service_id]
    config = Config(str(MIGRATION_ROOT / "configs" / f"{service_id}.ini"))
    with _coordination_connection() as connection:
        service_versions = _read_versions(
            adoption.service_version_table,
            connection=connection,
        )
        if service_versions is None:
            raise RuntimeError(f"{service_id} baseline has not been adopted")
        branch_head = tuple(ScriptDirectory.from_config(config).get_heads())
        if service_versions != branch_head:
            raise RuntimeError(
                f"{service_id} rollback must start at exact branch head {branch_head}; "
                f"observed {service_versions}"
            )
        _require_dependents_at_baseline(
            service_id,
            ownership,
            adoptions,
            connection=connection,
        )
        connection.commit()
        config.attributes["connection"] = connection
        command.downgrade(config, revision)
        resulting_versions = _read_versions(
            adoption.service_version_table,
            connection=connection,
        )
        if resulting_versions != (adoption.baseline_revision,):
            raise RuntimeError(
                f"{service_id} rollback did not produce exact head "
                f"{adoption.baseline_revision}; observed {resulting_versions}"
            )
        legacy_owned_tables = tuple(
            table
            for table, owner in ownership.table_migrators.items()
            if owner == service_id and table in legacy_tables
        )
        observed_schema = _live_schema_fingerprint(
            service_id,
            legacy_owned_tables,
            connection=connection,
        )
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
        _write_json_atomic(evidence_output, evidence)


def main(argv: list[str] | None = None) -> int:
    """Validate ownership, then dispatch one bounded Alembic command."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.service == "all" and args.command not in {"validate", "upgrade"}:
        parser.error("service 'all' is valid only with validate or upgrade")
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
    if args.service == "all":
        if args.revision != "head" or args.sql:
            parser.error("service 'all' upgrade requires live revision 'head'")
        for ordered_service in migration_order(ownership, SERVICE_IDS):
            _upgrade_service(
                ordered_service,
                revision="head",
                sql=False,
                ownership=ownership,
                adoptions=adoptions,
            )
        return 0

    service_id = cast(str, args.service)
    adoption = adoptions[service_id]
    config = Config(str(MIGRATION_ROOT / "configs" / f"{service_id}.ini"))
    legacy_owned_tables = tuple(
        table
        for table, owner in ownership.table_migrators.items()
        if owner == service_id and table in inventory.table_sources
    )
    if args.command == "heads":
        command.heads(config)
    elif args.command == "history":
        command.history(config)
    elif args.command == "current":
        command.current(config)
    elif args.command == "prepare-adoption":
        _prepare_adoption_evidence(
            service_id,
            adoption=adoption,
            expected_schema_fingerprint=schema_contract[service_id].digest,
            legacy_owned_tables=legacy_owned_tables,
            evidence_output=args.evidence_output,
            schema_output=args.schema_output,
            rollback_reference=args.rollback_reference,
        )
    elif args.command == "stamp-baseline":
        _stamp_service_baseline(
            service_id,
            adoption=adoption,
            expected_schema_fingerprint=schema_contract[service_id].digest,
            legacy_owned_tables=legacy_owned_tables,
            evidence=args.evidence,
        )
    elif args.command == "upgrade":
        _upgrade_service(
            service_id,
            revision=args.revision,
            sql=args.sql,
            ownership=ownership,
            adoptions=adoptions,
        )
    elif args.command == "downgrade":
        rollback_reference = args.rollback_reference.resolve()
        if not rollback_reference.is_file():
            raise RuntimeError("--rollback-reference must resolve to a persisted file")
        if args.revision != adoption.baseline_revision:
            raise RuntimeError(
                f"{service_id} rollback target must be exact baseline {adoption.baseline_revision}"
            )
        _downgrade_service(
            service_id,
            revision=args.revision,
            rollback_reference=rollback_reference,
            evidence_output=args.evidence_output,
            ownership=ownership,
            adoptions=adoptions,
            schema_contract=schema_contract,
            legacy_tables=frozenset(inventory.table_sources),
        )
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
