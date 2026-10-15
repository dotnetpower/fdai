"""Read-only, same-schema gate executed by Python in the signed Core image.

No DDL, catalog writes, source download, downgrade, or model initialization.
Only stable reason codes reach stdout/stderr, never the database exception or DSN.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError


def check_heads(connection: Connection, configs: list[Path]) -> bool:
    """Compare database heads with image-owned heads without invoking a migration."""

    for path in configs:
        config = Config(str(path))
        expected = set(ScriptDirectory.from_config(config).get_heads())
        actual = set(
            MigrationContext.configure(
                connection,
                opts={"version_table": config.get_main_option("version_table", "alembic_version")},
            ).get_current_heads()
        )
        if not expected or actual != expected:
            return False
    return True


def schema_configs(root: Path) -> list[Path]:
    """Resolve image-owned migration configs through the canonical ownership inventory."""

    sys.path.insert(0, str(root / "service-migrations"))
    from service_migrations.inventory import (  # type: ignore[import-not-found]
        load_legacy_inventory,
    )
    from service_migrations.ownership import (  # type: ignore[import-not-found]
        SERVICE_IDS,
        load_ownership_manifest,
        migration_order,
    )

    inventory = load_legacy_inventory(root / "alembic/versions")
    order = migration_order(
        load_ownership_manifest(root / "service-migrations/ownership.json", inventory), SERVICE_IDS
    )
    return [root / "alembic.ini"] + [
        root / f"service-migrations/configs/{service}.ini" for service in order
    ]


def main() -> int:
    configs = schema_configs(Path("/app"))
    url = os.environ.get("FDAI_DATABASE_URL", "")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    if not url.startswith("postgresql+psycopg://"):
        print("schema_check_configuration_invalid", file=sys.stderr)
        return 1
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        with engine.connect() as connection:
            connection.execute(text("SET statement_timeout = '10s'"))
            connection.execute(text("SET TRANSACTION READ ONLY"))
            if not check_heads(connection, configs):
                print("schema_check_mismatch", file=sys.stderr)
                return 1
    except (SQLAlchemyError, ValueError):
        print("schema_check_database_unavailable", file=sys.stderr)
        return 1
    print("schema_check_verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
