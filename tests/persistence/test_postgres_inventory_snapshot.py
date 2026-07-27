"""Integration tests for atomic PostgreSQL inventory promotion."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from fdai.delivery.persistence.postgres_inventory_delta import (
    PostgresInventoryDeltaProjector,
    _acquire_inventory_gate,
    _acquire_inventory_locks,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    _PROMOTION_LOCK,
    PostgresInventoryAgeProvider,
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


def _after_snapshot(manifest: InventoryCoverageManifest, seconds: int) -> str:
    assert manifest.started_at is not None
    return (manifest.started_at + timedelta(seconds=seconds)).isoformat()


async def test_inventory_delta_lock_serializes_the_same_resource() -> None:
    async with (
        await psycopg.AsyncConnection.connect(_dsn()) as first,
        await psycopg.AsyncConnection.connect(_dsn()) as second,
        first.transaction(),
    ):
        await _acquire_inventory_locks(first, ("resource-lock-shared",))
        async with second.transaction():
            await second.execute("SET LOCAL lock_timeout = '100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                await _acquire_inventory_locks(second, ("resource-lock-shared",))


async def test_inventory_delta_lock_allows_independent_resources() -> None:
    async with (
        await psycopg.AsyncConnection.connect(_dsn()) as first,
        await psycopg.AsyncConnection.connect(_dsn()) as second,
        first.transaction(),
        second.transaction(),
    ):
        await _acquire_inventory_locks(first, ("resource-lock-a",))
        await second.execute("SET LOCAL lock_timeout = '100ms'")
        await _acquire_inventory_locks(second, ("resource-lock-b",))


async def test_inventory_promotion_lock_blocks_delta_projection() -> None:
    async with (
        await psycopg.AsyncConnection.connect(_dsn()) as promotion,
        await psycopg.AsyncConnection.connect(_dsn()) as delta,
        promotion.transaction(),
    ):
        await promotion.execute("SELECT pg_advisory_xact_lock(%s)", (_PROMOTION_LOCK,))
        async with delta.transaction():
            await delta.execute("SET LOCAL lock_timeout = '100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                await _acquire_inventory_locks(delta, ("resource-lock-delta",))


async def test_inventory_graph_reconciliation_blocks_ordinary_patch() -> None:
    async with (
        await psycopg.AsyncConnection.connect(_dsn()) as reconciliation,
        await psycopg.AsyncConnection.connect(_dsn()) as patch,
        reconciliation.transaction(),
    ):
        await _acquire_inventory_gate(reconciliation, exclusive_graph=True)
        async with patch.transaction():
            await patch.execute("SET LOCAL lock_timeout = '100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                await _acquire_inventory_locks(patch, ("resource-lock-patch",))


async def test_failed_candidate_retains_last_active_snapshot() -> None:
    _upgrade()
    config = PostgresInventorySnapshotStoreConfig(dsn=_dsn())
    store = PostgresInventorySnapshotStore(config=config)
    provider = PostgresInventoryGraphProvider(config=config)
    context_provider = PostgresInventoryContextProvider(config=config)

    first = await store.begin(_manifest("arg"))
    await store.stage(
        first,
        InventoryBatch(
            resources=(
                ResourceRecord(
                    "rg-test",
                    "resource-group",
                    {
                        "name": "rg",
                        "tags": {"fdai:managed": "true", "fdai:workload": "fdai"},
                    },
                ),
            )
        ),
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
    assert context["props"] == {
        "name": "rg",
        "tags": {"fdai:managed": "true", "fdai:workload": "fdai"},
    }
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
                    "last_seen": _after_snapshot(manifest, 1),
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
                    "last_seen": _after_snapshot(manifest, 2),
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
    async with await psycopg.AsyncConnection.connect(_dsn()) as connection:
        cursor = await connection.execute(
            "SELECT change_kind FROM inventory_realtime_link "
            "WHERE from_id=%s AND link_type='contains' AND to_id=%s",
            ("rg-overlay", "rg-overlay/vm-old"),
        )
        assert await cursor.fetchone() == ("delete",)


async def test_complete_relationship_set_tombstones_missing_owned_link() -> None:
    _upgrade()
    config = PostgresInventorySnapshotStoreConfig(dsn=_dsn())
    store = PostgresInventorySnapshotStore(config=config)
    projector = PostgresInventoryDeltaProjector(config=config)
    manifest = _manifest("arg")
    attempt = await store.begin(manifest)
    await store.stage(
        attempt,
        InventoryBatch(
            resources=(
                ResourceRecord("rg-complete", "resource-group"),
                ResourceRecord("rg-complete/vm", "compute.vm"),
            ),
            links=(
                LinkRecord(
                    from_id="rg-complete/vm",
                    from_type="compute.vm",
                    link_type="depends_on",
                    to_id="rg-complete",
                    to_type="resource-group",
                ),
            ),
        ),
    )
    await store.promote(attempt, manifest)

    await projector(
        {
            "event_id": "event-complete-links",
            "idempotency_key": "inventory-complete-links",
            "inventory_change": {
                "kind": "upsert",
                "resource": {
                    "resource_id": "rg-complete/vm",
                    "type": "compute.vm",
                    "props": {},
                    "provider_ref": None,
                    "last_seen": _after_snapshot(manifest, 1),
                },
                "links_complete": True,
                "links": [],
            },
        }
    )

    async with await psycopg.AsyncConnection.connect(_dsn()) as connection:
        cursor = await connection.execute(
            "SELECT change_kind FROM inventory_realtime_link "
            "WHERE from_id=%s AND link_type='depends_on' AND to_id=%s",
            ("rg-complete/vm", "rg-complete"),
        )
        assert await cursor.fetchone() == ("delete",)


async def test_stale_resource_delete_does_not_tombstone_current_relationships() -> None:
    _upgrade()
    config = PostgresInventorySnapshotStoreConfig(dsn=_dsn())
    store = PostgresInventorySnapshotStore(config=config)
    projector = PostgresInventoryDeltaProjector(config=config)
    manifest = _manifest("arg")
    attempt = await store.begin(manifest)
    await store.stage(
        attempt,
        InventoryBatch(
            resources=(
                ResourceRecord("rg-ordering", "resource-group"),
                ResourceRecord("rg-ordering/vm", "compute.vm"),
            ),
            links=(
                LinkRecord(
                    from_id="rg-ordering",
                    from_type="resource-group",
                    link_type="contains",
                    to_id="rg-ordering/vm",
                    to_type="compute.vm",
                ),
            ),
        ),
    )
    await store.promote(attempt, manifest)

    async def project(event_id: str, kind: str, seconds: int) -> None:
        await projector(
            {
                "event_id": event_id,
                "idempotency_key": f"inventory-stale-{event_id}",
                "inventory_change": {
                    "kind": kind,
                    "resource": {
                        "resource_id": "rg-ordering/vm",
                        "type": "compute.vm",
                        "props": {},
                        "provider_ref": None,
                        "last_seen": _after_snapshot(manifest, seconds),
                    },
                    "links": [],
                },
            }
        )

    await project("event-newer", "upsert", 2)
    await project("event-stale", "delete", 1)

    async with await psycopg.AsyncConnection.connect(_dsn()) as connection:
        resource_cursor = await connection.execute(
            "SELECT change_kind FROM inventory_realtime_resource WHERE resource_id=%s",
            ("rg-ordering/vm",),
        )
        assert await resource_cursor.fetchone() == ("upsert",)
        link_cursor = await connection.execute(
            "SELECT change_kind FROM inventory_realtime_link "
            "WHERE from_id=%s AND link_type='contains' AND to_id=%s",
            ("rg-ordering", "rg-ordering/vm"),
        )
        assert await link_cursor.fetchone() is None


async def test_realtime_overlay_rejects_dangling_relationship() -> None:
    _upgrade()
    config = PostgresInventorySnapshotStoreConfig(dsn=_dsn())
    store = PostgresInventorySnapshotStore(config=config)
    projector = PostgresInventoryDeltaProjector(config=config)
    manifest = _manifest("arg")
    attempt = await store.begin(manifest)
    await store.stage(
        attempt,
        InventoryBatch(
            resources=(ResourceRecord("rg-dangling/vm", "compute.vm"),),
        ),
    )
    await store.promote(attempt, manifest)

    with pytest.raises(ValueError, match="relationship endpoint is missing"):
        await projector(
            {
                "event_id": "event-dangling-link",
                "idempotency_key": "inventory-dangling-link",
                "inventory_change": {
                    "kind": "upsert",
                    "resource": {
                        "resource_id": "rg-dangling/vm",
                        "type": "compute.vm",
                        "props": {"candidate": True},
                        "provider_ref": None,
                        "last_seen": _after_snapshot(manifest, 1),
                    },
                    "links": [
                        {
                            "change_kind": "upsert",
                            "from_id": "rg-dangling/vm",
                            "from_type": "compute.vm",
                            "link_type": "depends_on",
                            "to_id": "database-missing",
                            "to_type": "resource-group",
                            "props": {},
                        }
                    ],
                },
            }
        )

    async with await psycopg.AsyncConnection.connect(_dsn()) as connection:
        cursor = await connection.execute(
            "SELECT 1 FROM inventory_realtime_resource WHERE resource_id=%s",
            ("rg-dangling/vm",),
        )
        assert await cursor.fetchone() is None


async def test_realtime_overlay_rejects_relationship_endpoint_type_mismatch() -> None:
    _upgrade()
    config = PostgresInventorySnapshotStoreConfig(dsn=_dsn())
    store = PostgresInventorySnapshotStore(config=config)
    projector = PostgresInventoryDeltaProjector(config=config)
    manifest = _manifest("arg")
    attempt = await store.begin(manifest)
    await store.stage(
        attempt,
        InventoryBatch(
            resources=(
                ResourceRecord("rg-type-check", "resource-group"),
                ResourceRecord("rg-type-check/vm", "compute.vm"),
            ),
        ),
    )
    await store.promote(attempt, manifest)

    with pytest.raises(ValueError, match="endpoint type does not match"):
        await projector(
            {
                "event_id": "event-link-type-mismatch",
                "idempotency_key": "inventory-link-type-mismatch",
                "inventory_change": {
                    "kind": "upsert",
                    "resource": {
                        "resource_id": "rg-type-check/vm",
                        "type": "compute.vm",
                        "props": {"candidate": True},
                        "provider_ref": None,
                        "last_seen": _after_snapshot(manifest, 1),
                    },
                    "links": [
                        {
                            "change_kind": "upsert",
                            "from_id": "rg-type-check/vm",
                            "from_type": "compute.vm",
                            "link_type": "depends_on",
                            "to_id": "rg-type-check",
                            "to_type": "compute.vm",
                            "props": {},
                        }
                    ],
                },
            }
        )

    async with await psycopg.AsyncConnection.connect(_dsn()) as connection:
        cursor = await connection.execute(
            "SELECT 1 FROM inventory_realtime_resource WHERE resource_id=%s",
            ("rg-type-check/vm",),
        )
        assert await cursor.fetchone() is None


async def test_realtime_overlay_equal_timestamps_use_event_id_tiebreaker() -> None:
    _upgrade()
    config = PostgresInventorySnapshotStoreConfig(dsn=_dsn())
    store = PostgresInventorySnapshotStore(config=config)
    projector = PostgresInventoryDeltaProjector(config=config)
    context_provider = PostgresInventoryContextProvider(config=config)

    manifest = _manifest("arg")
    attempt = await store.begin(manifest)
    await store.stage(
        attempt,
        InventoryBatch(
            resources=(ResourceRecord("rg-tie/vm", "compute.vm", {"name": "base"}),),
        ),
    )
    await store.promote(attempt, manifest)

    observed_at = _after_snapshot(manifest, 1)

    async def project(event_id: str, name: str, *, kind: str = "upsert") -> None:
        await projector(
            {
                "event_id": event_id,
                "idempotency_key": f"inventory-tie-{event_id}",
                "inventory_change": {
                    "kind": kind,
                    "resource": {
                        "resource_id": "rg-tie/vm",
                        "type": "compute.vm",
                        "props": {"name": name},
                        "provider_ref": None,
                        "last_seen": observed_at,
                    },
                    "links": [],
                },
            }
        )

    await project("event-z", "winner")
    await project("event-a", "late-loser")

    context = await context_provider("rg-tie/vm")
    assert context is not None
    assert context["props"] == {"name": "winner"}

    await project("event-a", "deleted", kind="delete")
    assert await context_provider("rg-tie/vm") is None
    await project("event-zz", "must-not-resurrect")
    assert await context_provider("rg-tie/vm") is None


async def test_realtime_overlay_makes_graph_freshness_unknown_until_reconciliation() -> None:
    _upgrade()
    config = PostgresInventorySnapshotStoreConfig(dsn=_dsn())
    store = PostgresInventorySnapshotStore(config=config)
    projector = PostgresInventoryDeltaProjector(config=config)
    age_provider = PostgresInventoryAgeProvider(config=config)

    now = datetime.now(tz=UTC)
    manifest = InventoryCoverageManifest(
        source="arg",
        scopes=("scope-test",),
        resource_types=("compute.vm",),
        started_at=now,
        completed_at=now,
        metadata={"link_types": ("contains", "attached_to", "depends_on")},
    )
    attempt = await store.begin(manifest)
    await store.stage(
        attempt,
        InventoryBatch(resources=(ResourceRecord("rg-fresh/vm", "compute.vm"),)),
    )
    await store.promote(attempt, manifest)
    assert await age_provider("rg-fresh/vm") is not None

    await projector(
        {
            "event_id": "event-realtime",
            "idempotency_key": "inventory-realtime",
            "inventory_change": {
                "kind": "upsert",
                "resource": {
                    "resource_id": "rg-fresh/vm",
                    "type": "compute.vm",
                    "props": {"name": "changed"},
                    "provider_ref": None,
                    "last_seen": (now + timedelta(seconds=1)).isoformat(),
                },
                "links": [],
            },
        }
    )

    assert await age_provider("rg-fresh/vm") is None


async def test_realtime_overlay_ignores_event_covered_by_active_snapshot() -> None:
    _upgrade()
    config = PostgresInventorySnapshotStoreConfig(dsn=_dsn())
    store = PostgresInventorySnapshotStore(config=config)
    projector = PostgresInventoryDeltaProjector(config=config)
    context_provider = PostgresInventoryContextProvider(config=config)

    manifest = _manifest("arg")
    attempt = await store.begin(manifest)
    await store.stage(
        attempt,
        InventoryBatch(
            resources=(ResourceRecord("rg-stale/vm", "compute.vm", {"name": "snapshot"}),),
        ),
    )
    await store.promote(attempt, manifest)
    assert manifest.started_at is not None

    result = await projector(
        {
            "event_id": "event-before-snapshot",
            "idempotency_key": "inventory-before-snapshot",
            "inventory_change": {
                "kind": "upsert",
                "resource": {
                    "resource_id": "rg-stale/vm",
                    "type": "compute.vm",
                    "props": {"name": "stale-event"},
                    "provider_ref": None,
                    "last_seen": (manifest.started_at - timedelta(seconds=1)).isoformat(),
                },
                "links": [],
            },
        }
    )

    assert result.resources == 0
    assert result.links == 0
    context = await context_provider("rg-stale/vm")
    assert context is not None
    assert context["props"] == {"name": "snapshot"}
