"""Fail-closed dispatcher for five independently runnable migration branches."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import cast

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from service_migrations.inventory import load_legacy_inventory
from service_migrations.ownership import SERVICE_IDS, load_ownership_manifest
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
    downgrade.add_argument("--rollback-reference", required=True)
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


def _validate_evidence(path: Path, *, service_id: str, head: str, count: int) -> str:
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
    for key in ("verified_at", "rollback_reference"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"adoption evidence {key} is required")
    return cast(str, raw["rollback_reference"])


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
        _validate_evidence(
            args.evidence,
            service_id=service_id,
            head=adoption.required_legacy_head,
            count=adoption.legacy_revision_count,
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
        command.stamp(config, adoption.baseline_revision)
    elif args.command == "upgrade":
        if not args.sql:
            service_versions = _read_versions(adoption.service_version_table)
            if service_versions is None or adoption.baseline_revision not in service_versions:
                raise RuntimeError(
                    f"{service_id} baseline is not stamped; run stamp-baseline first"
                )
        command.upgrade(config, args.revision, sql=args.sql)
    elif args.command == "downgrade":
        if not args.rollback_reference.strip():
            raise RuntimeError("--rollback-reference must be non-empty")
        service_versions = _read_versions(adoption.service_version_table)
        if service_versions is None:
            raise RuntimeError(f"{service_id} baseline has not been adopted")
        command.downgrade(config, args.revision)
    else:  # pragma: no cover - argparse constrains commands
        raise AssertionError(args.command)
    return 0
