"""Integration tests for atomic PostgreSQL inventory promotion."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fdai.delivery.persistence.postgres_inventory_delta import (
    PostgresInventoryDeltaProjector,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventoryContextProvider,
    PostgresInventoryGraphProvider,
    PostgresInventorySnapshotStore,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.providers.inventory import InventoryBatch, LinkRecord, ResourceRecord
from fdai.shared.providers.inventory_snapshot import (
    InventoryAttemptFailure,
    InventoryCoverageManifest,
    InventoryFailureCode,
)

pytestmark = pytest.mark.integration
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _dsn() -> str:
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade() -> None:
    _dsn()
    result = subprocess.run(  # noqa: S603 - controlled migration command
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _manifest(source: str) -> InventoryCoverageManifest:
    return InventoryCoverageManifest(
        source=source,
        scopes=("scope-test",),
        resource_types=("resource-group", "compute.vm"),
        started_at=datetime.now(tz=UTC),
        completed_at=datetime.now(tz=UTC),
    )


async def test_failed_candidate_retains_last_active_snapshot() -> None:
    _upgrade()
    config = PostgresInventorySnapshotStoreConfig(dsn=_dsn())
    store = PostgresInventorySnapshotStore(config=config)
    provider = PostgresInventoryGraphProvider(config=config)
    context_provider = PostgresInventoryContextProvider(config=config)

    first = await store.begin(_manifest("arg"))
    await store.stage(
        first,
        InventoryBatch(resources=(ResourceRecord("rg-test", "resource-group", {"name": "rg"}),)),
    )
    await store.promote(first, _manifest("arg"))

    second = await store.begin(_manifest("arm"))
    await store.stage(
        second,
        InventoryBatch(resources=(ResourceRecord("vm-test", "compute.vm", {"name": "vm"}),)),
    )
    await store.fail(
        second,
        InventoryAttemptFailure(InventoryFailureCode.NETWORK_BLOCKED, "ConnectTimeout"),
    )

    graph = await provider(None, 4, ("contains",))
    assert graph["source"] == "arg"
    assert [resource["id"] for resource in graph["resources"]] == ["rg-test"]
    context = await context_provider("rg-test")
    assert context is not None
    assert context["resource_type"] == "resource-group"
    assert context["props"] == {"name": "rg"}
    assert await context_provider("missing-resource") is None


async def test_promotion_rejects_dangling_link() -> None:
    _upgrade()
    store = PostgresInventorySnapshotStore(config=PostgresInventorySnapshotStoreConfig(dsn=_dsn()))
    attempt = await store.begin(_manifest("arg"))
    await store.stage(
        attempt,
        InventoryBatch(
            resources=(ResourceRecord("vm-link-test", "compute.vm"),),
            links=(
                LinkRecord(
                    from_id="missing-rg",
                    from_type="resource-group",
                    link_type="contains",
                    to_id="vm-link-test",
                    to_type="compute.vm",
                ),
            ),
        ),
    )
    with pytest.raises(ValueError, match="missing endpoint"):
        await store.promote(attempt, _manifest("arg"))


async def test_realtime_overlay_upsert_and_delete_override_active_snapshot() -> None:
    _upgrade()
    config = PostgresInventorySnapshotStoreConfig(dsn=_dsn())
    store = PostgresInventorySnapshotStore(config=config)
    projector = PostgresInventoryDeltaProjector(config=config)
    graph_provider = PostgresInventoryGraphProvider(config=config)
    context_provider = PostgresInventoryContextProvider(config=config)

    manifest = _manifest("arg")
    attempt = await store.begin(manifest)
    await store.stage(
        attempt,
        InventoryBatch(
            resources=(
                ResourceRecord("rg-overlay", "resource-group", {"name": "rg"}),
                ResourceRecord("rg-overlay/vm-old", "compute.vm", {"name": "old"}),
            ),
            links=(
                LinkRecord(
                    from_id="rg-overlay",
                    from_type="resource-group",
                    link_type="contains",
                    to_id="rg-overlay/vm-old",
                    to_type="compute.vm",
                ),
            ),
        ),
    )
    await store.promote(attempt, manifest)

    await projector(
        {
            "event_id": "event-upsert",
            "idempotency_key": "inventory-upsert",
            "inventory_change": {
                "kind": "upsert",
                "resource": {
                    "resource_id": "rg-overlay/vm-new",
                    "type": "compute.vm",
                    "props": {"name": "new"},
                    "provider_ref": "/subscriptions/example/resourceGroups/rg/vm-new",
                    "last_seen": "2026-07-18T02:00:00Z",
                },
                "links": [
                    {
                        "change_kind": "upsert",
                        "from_id": "rg-overlay",
                        "from_type": "resource-group",
                        "link_type": "contains",
                        "to_id": "rg-overlay/vm-new",
                        "to_type": "compute.vm",
                        "props": {},
                    }
                ],
            },
        }
    )
    await projector(
        {
            "event_id": "event-delete",
            "idempotency_key": "inventory-delete",
            "inventory_change": {
                "kind": "delete",
                "resource": {
                    "resource_id": "rg-overlay/vm-old",
                    "type": "compute.vm",
                    "props": {},
                    "provider_ref": "/subscriptions/example/resourceGroups/rg/vm-old",
                    "last_seen": "2026-07-18T02:01:00Z",
                },
                "links": [],
            },
        }
    )

    graph = await graph_provider("rg-overlay", 2, ("contains",))
    ids = {resource["id"] for resource in graph["resources"]}
    assert "rg-overlay/vm-new" in ids
    assert "rg-overlay/vm-old" not in ids
    assert graph["realtime"]["pending_changes"] == 2
    assert await context_provider("rg-overlay/vm-old") is None
    context = await context_provider("rg-overlay/vm-new")
    assert context is not None
    assert context["props"] == {"name": "new"}
