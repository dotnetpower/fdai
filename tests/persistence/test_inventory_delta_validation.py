"""Boundary and ordering tests for real-time inventory delta projection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, call

import pytest

from fdai.delivery.persistence.postgres_inventory_delta import (
    _GRAPH_RECONCILIATION_LOCK,
    _RESOURCE_LOCK_SEED,
    PostgresInventoryDeltaProjector,
    _acquire_inventory_locks,
    _covered_resource_types,
    _lock_resource_ids,
    _prefer_incoming_change,
    _reconcile_links,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    _PROMOTION_LOCK,
    PostgresInventorySnapshotStoreConfig,
)

_NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def _payload(
    *,
    kind: str = "upsert",
    observed_at: datetime = _NOW,
    links: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "event_id": "event-1",
        "idempotency_key": "inventory-event-1",
        "inventory_change": {
            "kind": kind,
            "resource": {
                "resource_id": "rg-one/vm-one",
                "type": "compute.vm",
                "props": {},
                "provider_ref": None,
                "last_seen": observed_at.isoformat(),
            },
            "links": links or [],
        },
    }


def _link(*, change_kind: str = "upsert") -> dict[str, object]:
    return {
        "change_kind": change_kind,
        "from_id": "rg-one",
        "from_type": "resource-group",
        "link_type": "contains",
        "to_id": "rg-one/vm-one",
        "to_type": "compute.vm",
        "props": {},
    }


async def test_future_observation_is_rejected_before_database_work() -> None:
    projector = PostgresInventoryDeltaProjector(
        config=PostgresInventorySnapshotStoreConfig(dsn="postgresql://unused"),
        clock=lambda: _NOW,
        max_future_skew_seconds=300,
    )

    with pytest.raises(ValueError, match="future skew"):
        await projector(_payload(observed_at=_NOW + timedelta(seconds=301)))


async def test_link_count_is_bounded_before_database_work() -> None:
    projector = PostgresInventoryDeltaProjector(
        config=PostgresInventorySnapshotStoreConfig(dsn="postgresql://unused"),
        clock=lambda: _NOW,
        max_links=1,
    )

    with pytest.raises(ValueError, match="links exceeds cap"):
        await projector(_payload(links=[_link(), _link()]))


async def test_resource_delete_rejects_link_upsert() -> None:
    projector = PostgresInventoryDeltaProjector(
        config=PostgresInventorySnapshotStoreConfig(dsn="postgresql://unused"),
        clock=lambda: _NOW,
    )

    with pytest.raises(ValueError, match="resource delete.*link deletes"):
        await projector(_payload(kind="delete", links=[_link(change_kind="upsert")]))


def test_coverage_set_includes_resource_and_link_endpoint_types() -> None:
    covered = _covered_resource_types("compute.vm", [_link()])

    assert covered == ("compute.vm", "resource-group")


def test_lock_resource_ids_are_deduplicated_and_sorted() -> None:
    links = [
        _link(),
        {
            **_link(),
            "from_id": "z-database",
            "to_id": "rg-one/vm-one",
            "link_type": "depends_on",
        },
    ]

    assert _lock_resource_ids("rg-one/vm-one", links) == (
        "rg-one",
        "rg-one/vm-one",
        "z-database",
    )


async def test_inventory_locks_take_promotion_gate_then_sorted_resource_locks() -> None:
    connection = AsyncMock()

    await _acquire_inventory_locks(connection, ("z-resource", "a-resource", "z-resource"))

    assert connection.execute.await_args_list == [
        call("SELECT pg_advisory_xact_lock_shared(%s)", (_PROMOTION_LOCK,)),
        call(
            "SELECT pg_advisory_xact_lock_shared(%s)",
            (_GRAPH_RECONCILIATION_LOCK,),
        ),
        call(
            "SELECT pg_advisory_xact_lock(-1 - (hashtextextended(%s, %s) & 9223372036854775807))",
            ("a-resource", _RESOURCE_LOCK_SEED),
        ),
        call(
            "SELECT pg_advisory_xact_lock(-1 - (hashtextextended(%s, %s) & 9223372036854775807))",
            ("z-resource", _RESOURCE_LOCK_SEED),
        ),
    ]


async def test_delete_reconciles_all_incident_links_to_tombstones() -> None:
    connection = AsyncMock()
    connection.execute.return_value.fetchall.return_value = [
        {
            "from_id": "rg-one",
            "from_type": "resource-group",
            "link_type": "contains",
            "to_id": "rg-one/vm-one",
            "to_type": "compute.vm",
            "props": {},
        },
        {
            "from_id": "rg-one/vm-one",
            "from_type": "compute.vm",
            "link_type": "depends_on",
            "to_id": "database-one",
            "to_type": "postgresql",
            "props": {},
        },
    ]

    links = await _reconcile_links(
        connection,
        snapshot_id="snapshot-one",
        resource_id="rg-one/vm-one",
        change_kind="delete",
        links_complete=False,
        incoming=(),
        max_links=10,
    )

    assert [link["change_kind"] for link in links] == ["delete", "delete"]


async def test_complete_links_tombstone_only_missing_owned_relationships() -> None:
    connection = AsyncMock()
    connection.execute.return_value.fetchall.return_value = [
        {
            "from_id": "rg-one/vm-one",
            "from_type": "compute.vm",
            "link_type": "depends_on",
            "to_id": "database-old",
            "to_type": "postgresql",
            "props": {},
        }
    ]
    incoming = (
        {
            "change_kind": "upsert",
            "from_id": "rg-one/vm-one",
            "from_type": "compute.vm",
            "link_type": "depends_on",
            "to_id": "database-new",
            "to_type": "postgresql",
            "props": {},
        },
    )

    links = await _reconcile_links(
        connection,
        snapshot_id="snapshot-one",
        resource_id="rg-one/vm-one",
        change_kind="upsert",
        links_complete=True,
        incoming=incoming,
        max_links=10,
    )

    assert [(link["to_id"], link["change_kind"]) for link in links] == [
        ("database-new", "upsert"),
        ("database-old", "delete"),
    ]


@pytest.mark.parametrize(
    ("current_kind", "current_event", "incoming_kind", "incoming_event", "expected"),
    [
        ("upsert", "event-z", "delete", "event-a", True),
        ("delete", "event-a", "upsert", "event-z", False),
        ("upsert", "event-a", "upsert", "event-z", True),
        ("delete", "event-z", "delete", "event-a", False),
    ],
)
def test_equal_time_ordering_prefers_delete_then_event_id(
    current_kind: str,
    current_event: str,
    incoming_kind: str,
    incoming_event: str,
    expected: bool,
) -> None:
    assert (
        _prefer_incoming_change(
            current_kind=current_kind,
            current_event_id=current_event,
            incoming_kind=incoming_kind,
            incoming_event_id=incoming_event,
        )
        is expected
    )
