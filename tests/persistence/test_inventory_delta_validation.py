"""Boundary and ordering tests for real-time inventory delta projection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.delivery.persistence.postgres_inventory_delta import (
    PostgresInventoryDeltaProjector,
    _covered_resource_types,
    _prefer_incoming_change,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
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
