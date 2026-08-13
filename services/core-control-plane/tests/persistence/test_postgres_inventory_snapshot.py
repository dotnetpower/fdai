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
    InventoryDeltaApplyOutcome,
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
_REPO_ROOT = Path(__file__).resolve().parents[4]


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


@pytest.mark.parametrize("write_batch_size", [0, 10_001])
def test_inventory_snapshot_rejects_invalid_write_batch_size(write_batch_size: int) -> None:
    with pytest.raises(ValueError, match="write_batch_size"):
        PostgresInventorySnapshotStoreConfig(
            dsn="postgresql://example.invalid/fdai",
            write_batch_size=write_batch_size,
        )


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


async def test_inventory_coverage_summary_does_not_decode_resource_properties() -> None:
    _upgrade()
    config = PostgresInventorySnapshotStoreConfig(dsn=_dsn())
    store = PostgresInventorySnapshotStore(config=config)
    provider = PostgresInventoryGraphProvider(config=config)
    attempt = await store.begin(_manifest("arg"))
    await store.stage(
        attempt,
        InventoryBatch(
            resources=(
                ResourceRecord(
                    "vm-invalid-property",
                    "compute.vm",
                    {"shutdown_schedule": {"enabled": "not-a-boolean"}},
                ),
            )
        ),
    )
    await store.promote(attempt, _manifest("arg"))

    summary = await provider.coverage_summary(limit=10)

    assert summary["source"] == "arg"
    assert summary["resource_count"] == 1
    assert summary["link_count"] == 0
    assert summary["truncated"] is False


async def test_rooted_inventory_graph_respects_depth_and_limit() -> None:
    _upgrade()
    config = PostgresInventorySnapshotStoreConfig(dsn=_dsn())
    store = PostgresInventorySnapshotStore(config=config)
    provider = PostgresInventoryGraphProvider(config=config)
    manifest = _manifest("arg")
    attempt = await store.begin(manifest)
    await store.stage(
        attempt,
        InventoryBatch(
            resources=(
                ResourceRecord("bounded-root", "resource-group", {"name": "root"}),
                ResourceRecord("bounded-child-a", "compute.vm", {"name": "child-a"}),
                ResourceRecord("bounded-child-b", "compute.vm", {"name": "child-b"}),
                ResourceRecord("bounded-grandchild", "compute.vm", {"name": "grandchild"}),
                ResourceRecord("bounded-unrelated", "compute.vm", {"name": "unrelated"}),
            ),
            links=(
                LinkRecord(
                    from_id="bounded-root",
                    from_type="resource-group",
                    link_type="contains",
                    to_id="bounded-child-a",
                    to_type="compute.vm",
                ),
                LinkRecord(
                    from_id="bounded-root",
                    from_type="resource-group",
                    link_type="contains",
                    to_id="bounded-child-b",
                    to_type="compute.vm",
                ),
                LinkRecord(
                    from_id="bounded-child-a",
                    from_type="compute.vm",
                    link_type="depends_on",
                    to_id="bounded-grandchild",
                    to_type="compute.vm",
                ),
            ),
        ),
    )
    await store.promote(attempt, manifest)

    direct = await provider(
        None,
        1,
        ("contains", "depends_on"),
        root="bounded-root",
        limit=10,
    )
    assert {resource["id"] for resource in direct["resources"]} == {
        "bounded-root",
        "bounded-child-a",
        "bounded-child-b",
    }
    assert direct["truncated"] is False

    transitive = await provider(
        None,
        2,
        ("contains", "depends_on"),
        root="bounded-root",
        limit=10,
    )
    assert {resource["id"] for resource in transitive["resources"]} == {
        "bounded-root",
        "bounded-child-a",
        "bounded-child-b",
        "bounded-grandchild",
    }
    assert transitive["truncated"] is False

    limited = await provider(
        None,
        2,
        ("contains", "depends_on"),
        root="bounded-root",
        limit=2,
    )
    assert len(limited["resources"]) == 2
    assert limited["resources"][0]["id"] == "bounded-root"
    assert limited["truncated"] is True
    assert limited["truncation_reasons"] == ["resource_limit"]


async def test_inventory_snapshot_stage_chunks_large_batches() -> None:
    _upgrade()

    class RecordingSnapshotStore(PostgresInventorySnapshotStore):
        batch_sizes: list[int]

        def __init__(self, *, config: PostgresInventorySnapshotStoreConfig) -> None:
            super().__init__(config=config)
            self.batch_sizes = []

        async def _executemany(
            self,
            cursor: psycopg.AsyncCursor[object],
            query: str,
            rows: list[tuple[object, ...]],
        ) -> None:
            self.batch_sizes.append(len(rows))
            await super()._executemany(cursor, query, rows)

    store = RecordingSnapshotStore(
        config=PostgresInventorySnapshotStoreConfig(dsn=_dsn(), write_batch_size=2)
    )
    attempt = await store.begin(_manifest("arg"))
    resource_ids = tuple(f"chunk-resource-{index}" for index in range(5))
    await store.stage(
        attempt,
        InventoryBatch(
            resources=tuple(
                ResourceRecord(resource_id, "compute.vm") for resource_id in resource_ids
            ),
            links=tuple(
                LinkRecord(
                    from_id=resource_ids[0],
                    from_type="compute.vm",
                    link_type="depends_on",
                    to_id=resource_id,
                    to_type="compute.vm",
                )
                for resource_id in resource_ids[1:]
            ),
        ),
    )

    assert store.batch_sizes == [2, 2, 1, 2, 2]


async def test_rooted_inventory_graph_expands_frontier_fairly() -> None:
    _upgrade()
    config = PostgresInventorySnapshotStoreConfig(dsn=_dsn())
    store = PostgresInventorySnapshotStore(config=config)
    provider = PostgresInventoryGraphProvider(config=config)
    manifest = _manifest("arg")
    attempt = await store.begin(manifest)
    child_ids = tuple(f"fair-a-child-{index:03d}" for index in range(65))
    await store.stage(
        attempt,
        InventoryBatch(
            resources=(
                ResourceRecord("fair-root", "resource-group"),
                ResourceRecord("fair-a", "compute.vm"),
                ResourceRecord("fair-z", "compute.vm"),
                *(ResourceRecord(child_id, "compute.vm") for child_id in child_ids),
                ResourceRecord("fair-z-child", "compute.vm"),
            ),
            links=(
                LinkRecord(
                    from_id="fair-root",
                    from_type="resource-group",
                    link_type="contains",
                    to_id="fair-a",
                    to_type="compute.vm",
                ),
                LinkRecord(
                    from_id="fair-root",
                    from_type="resource-group",
                    link_type="contains",
                    to_id="fair-z",
                    to_type="compute.vm",
                ),
                *(
                    LinkRecord(
                        from_id="fair-a",
                        from_type="compute.vm",
                        link_type="contains",
                        to_id=child_id,
                        to_type="compute.vm",
                    )
                    for child_id in child_ids
                ),
                LinkRecord(
                    from_id="fair-z",
                    from_type="compute.vm",
                    link_type="contains",
                    to_id="fair-z-child",
                    to_type="compute.vm",
                ),
            ),
        ),
    )
    await store.promote(attempt, manifest)

    graph = await provider(
        None,
        2,
        ("contains",),
        root="fair-root",
        limit=5,
    )

    assert [resource["id"] for resource in graph["resources"]] == [
        "fair-root",
        "fair-a",
        "fair-z",
        "fair-a-child-000",
        "fair-z-child",
    ]
    assert graph["truncated"] is True


async def test_inventory_graph_read_uses_consistent_read_only_transaction() -> None:
    _upgrade()
    config = PostgresInventorySnapshotStoreConfig(dsn=_dsn())

    class RecordingGraphProvider(PostgresInventoryGraphProvider):
        transaction_state: tuple[str, str] | None = None

        async def _set_timeout(self, connection: psycopg.AsyncConnection[object]) -> None:
            await super()._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT current_setting('transaction_isolation') AS isolation, "
                "current_setting('transaction_read_only') AS read_only"
            )
            row = await cursor.fetchone()
            assert row is not None
            self.transaction_state = (str(row["isolation"]), str(row["read_only"]))

    provider = RecordingGraphProvider(config=config)
    await provider(None, 1, ("contains",))

    assert provider.transaction_state == ("repeatable read", "on")


async def test_inventory_graph_reverse_indexes_are_migrated() -> None:
    _upgrade()
    async with await psycopg.AsyncConnection.connect(_dsn()) as connection:
        cursor = await connection.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname=current_schema() "
            "AND indexname=ANY(%s::text[]) ORDER BY indexname",
            (
                [
                    "idx_inventory_realtime_link_reverse",
                    "idx_inventory_snapshot_link_reverse",
                ],
            ),
        )

        assert [row[0] for row in await cursor.fetchall()] == [
            "idx_inventory_realtime_link_reverse",
            "idx_inventory_snapshot_link_reverse",
        ]


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

    async def project(event_id: str, kind: str, seconds: int) -> InventoryDeltaApplyOutcome:
        result = await projector(
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
        return result.outcome

    assert await project("event-newer", "upsert", 2) is InventoryDeltaApplyOutcome.APPLIED
    assert await project("event-stale", "delete", 1) is InventoryDeltaApplyOutcome.ORDERING_REJECTED

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


async def test_realtime_overlay_rejects_existing_resource_type_change() -> None:
    _upgrade()
    config = PostgresInventorySnapshotStoreConfig(dsn=_dsn())
    store = PostgresInventorySnapshotStore(config=config)
    projector = PostgresInventoryDeltaProjector(config=config)
    manifest = _manifest("arg")
    attempt = await store.begin(manifest)
    await store.stage(
        attempt,
        InventoryBatch(
            resources=(ResourceRecord("resource-type-stable", "compute.vm"),),
        ),
    )
    await store.promote(attempt, manifest)

    with pytest.raises(ValueError, match="resource type does not match"):
        await projector(
            {
                "event_id": "event-resource-type-change",
                "idempotency_key": "inventory-resource-type-change",
                "inventory_change": {
                    "kind": "upsert",
                    "resource": {
                        "resource_id": "resource-type-stable",
                        "type": "resource-group",
                        "props": {},
                        "provider_ref": None,
                        "last_seen": _after_snapshot(manifest, 1),
                    },
                    "links": [],
                },
            }
        )

    async with await psycopg.AsyncConnection.connect(_dsn()) as connection:
        cursor = await connection.execute(
            "SELECT 1 FROM inventory_realtime_resource WHERE resource_id=%s",
            ("resource-type-stable",),
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
    graph_provider = PostgresInventoryGraphProvider(config=config)

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
    graph = await graph_provider(None, 2, ("contains", "attached_to", "depends_on"))
    assert graph["freshness"] == "unknown"
    assert graph["degraded"] is True


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
    assert result.outcome is InventoryDeltaApplyOutcome.SNAPSHOT_COVERED
    context = await context_provider("rg-stale/vm")
    assert context is not None
    assert context["props"] == {"name": "snapshot"}
