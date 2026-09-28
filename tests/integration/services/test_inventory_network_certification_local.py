"""Local reproduction of the isolated inventory network certification data path.

The governed Azure campaign previously discovered schema and credential defects only
after a full publish, import, and execution cycle. This harness exercises the same
migration closure and inventory promotion locally so an equivalent defect fails in
seconds instead of a governed round trip. It uses a throwaway role and database and
never contacts a provider, Azure, or a model.
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

import psycopg
import pytest
from fdai.delivery.inventory_sync import InventorySyncCoordinator
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStore,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord
from fdai.shared.providers.inventory_snapshot import (
    InventoryCoverageManifest,
    InventorySource,
)
from psycopg import sql

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_RUNNER_PATH = (
    _ROOT / "scripts" / "deployment" / "azure" / "run_inventory_network_certification_migrations.py"
)
_SOURCE_REVISION = "0" * 40

# The governed sandbox generates a password containing URL-encoded characters. A
# percent token reproduces the ConfigParser interpolation class that broke both the
# legacy and the service-owned migration environments in live executions.
_PERCENT_PASSWORD = "Fdai-local%cert-7"


def _runner_module() -> object:
    spec = importlib.util.spec_from_file_location(
        "run_inventory_network_certification_migrations", _RUNNER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _admin_dsn() -> str:
    value = os.environ.get("FDAI_LOCAL_CERTIFICATION_ADMIN_DSN", "").strip()
    if not value:
        pytest.skip("FDAI_LOCAL_CERTIFICATION_ADMIN_DSN is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def certification_dsn() -> AsyncIterator[str]:
    """Provision an isolated role and database whose password needs escaping."""

    admin = _admin_dsn()
    role = _identifier("fdai_cert")
    database = _identifier("fdai_cert")
    with psycopg.connect(admin, autocommit=True, connect_timeout=10) as connection:
        # Azure runs this closure as the Flexible Server administrator, which owns the
        # extension allowlist and every service role. The local equivalent is a
        # disposable superuser role on the throwaway validation container; both the
        # role and its database are dropped in teardown.
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN SUPERUSER PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(_PERCENT_PASSWORD)
            )
        )
        connection.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(database), sql.Identifier(role)
            )
        )
    parts = urlsplit(admin)
    port = f":{parts.port}" if parts.port else ""
    dsn = (
        f"postgresql://{role}:{quote(_PERCENT_PASSWORD, safe='')}@{parts.hostname}{port}/{database}"
    )
    try:
        yield dsn
    finally:
        with psycopg.connect(admin, autocommit=True, connect_timeout=10) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database))
            )
            connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


def test_certification_migration_closure_survives_encoded_credentials(
    certification_dsn: str,
) -> None:
    """Both migration environments must accept a percent-bearing credential."""

    module = _runner_module()
    receipt = module.run_inventory_network_migrations(  # type: ignore[attr-defined]
        {
            **os.environ,
            "FDAI_DATABASE_URL": certification_dsn,
            "FDAI_NETWORK_CERT_SOURCE_REVISION": _SOURCE_REVISION,
        },
        repository_root=_ROOT,
    )

    assert receipt["services"]
    assert receipt["execution_authority"] is False
    with psycopg.connect(certification_dsn, connect_timeout=10) as connection:
        columns = connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='inventory_snapshot' "
            "AND column_name IN ('resource_count','link_count') ORDER BY column_name"
        ).fetchall()
        service_table = connection.execute(
            "SELECT to_regclass('public.alembic_version_core_control_plane') IS NOT NULL"
        ).fetchone()

    assert [row[0] for row in columns] == ["link_count", "resource_count"]
    assert service_table is not None and service_table[0] is True


async def test_isolated_certification_promotes_a_requested_resource_type_snapshot(
    certification_dsn: str,
) -> None:
    """The certification coordinator must promote its bounded snapshot end to end."""

    module = _runner_module()
    module.run_inventory_network_migrations(  # type: ignore[attr-defined]
        {
            **os.environ,
            "FDAI_DATABASE_URL": certification_dsn,
            "FDAI_NETWORK_CERT_SOURCE_REVISION": _SOURCE_REVISION,
        },
        repository_root=_ROOT,
    )

    class _Inventory:
        async def full_snapshot(self, since: str | None = None) -> AsyncIterator[InventoryBatch]:
            del since
            yield InventoryBatch(
                resources=(
                    ResourceRecord(resource_id="rg-local-certification", type="resource-group"),
                )
            )
            yield InventoryBatch(final=True)

    store = PostgresInventorySnapshotStore(
        config=PostgresInventorySnapshotStoreConfig(dsn=certification_dsn)
    )
    source = InventorySource(
        name="arg",
        inventory=_Inventory(),
        manifest=InventoryCoverageManifest(
            source="arg",
            scopes=("local-certification-scope",),
            resource_types=("resource-group",),
            started_at=datetime.now(tz=UTC),
            metadata={"coverage_scope": "requested_resource_types"},
        ),
    )

    result = await InventorySyncCoordinator.for_isolated_resource_type_certification(
        store=store
    ).run((source,))

    assert result.source == "arg"
    assert result.failures == ()
    assert await store.active_snapshot_id() == result.attempt_id
