"""Inventory Protocol structural + record-invariant tests.

Behavioural tests (adapter round-trip, delta ordering, idempotent
upsert) land with the Azure adapter in P2. This file asserts:

- The Protocol is importable from `fdai.shared.providers`.
- The record dataclasses are frozen and inert (no mutable defaults).
- A trivial in-memory implementation satisfies the Protocol structurally.
- `InventoryBatch.final` defaults to False so a partial stream can never
  masquerade as complete.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fdai.shared.providers import (
    Inventory,
    InventoryBatch,
    LinkRecord,
    ResourceRecord,
)
from fdai.shared.providers.state_evidence import LINK_OBSERVATION_METADATA_PROPERTY


def test_inventory_protocol_is_importable_and_runtime_checkable() -> None:
    """`isinstance` check against a Protocol is intentional here."""

    class _Empty:
        def full_snapshot(
            self, since: str | None = None
        ) -> AsyncIterator[InventoryBatch]:  # pragma: no cover - never invoked
            raise NotImplementedError

        def delta(
            self, cursor: str
        ) -> AsyncIterator[InventoryBatch]:  # pragma: no cover - never invoked
            raise NotImplementedError

    assert isinstance(_Empty(), Inventory)


def test_resource_record_is_frozen() -> None:
    record = ResourceRecord(resource_id="rid", type="compute.vm")
    with pytest.raises((AttributeError, TypeError)):
        record.type = "compute.function"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("resource_id", "resource_type"),
    [("", "compute.vm"), ("rid", "")],
)
def test_resource_record_rejects_blank_identity(resource_id: str, resource_type: str) -> None:
    with pytest.raises(ValueError, match="MUST be non-empty"):
        ResourceRecord(resource_id=resource_id, type=resource_type)


def test_resource_record_rejects_malformed_properties_and_timestamp() -> None:
    with pytest.raises(ValueError, match="props MUST be a mapping"):
        ResourceRecord(resource_id="rid", type="compute.vm", props=[])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="last_seen MUST be timezone-aware RFC 3339"):
        ResourceRecord(resource_id="rid", type="compute.vm", last_seen="2026-08-08T12:00:00")


def test_link_record_is_frozen() -> None:
    link = LinkRecord(
        from_id="a",
        from_type="resource-group",
        link_type="contains",
        to_id="b",
        to_type="compute.vm",
    )
    with pytest.raises((AttributeError, TypeError)):
        link.link_type = "attached_to"  # type: ignore[misc]


@pytest.mark.parametrize("field_name", ["from_id", "from_type", "link_type", "to_id", "to_type"])
def test_link_record_rejects_blank_identity(field_name: str) -> None:
    values = {
        "from_id": "a",
        "from_type": "resource-group",
        "link_type": "contains",
        "to_id": "b",
        "to_type": "compute.vm",
    }
    values[field_name] = ""
    with pytest.raises(ValueError, match="MUST be non-empty"):
        LinkRecord(**values)


def test_link_record_rejects_malformed_properties() -> None:
    with pytest.raises(ValueError, match="link_props MUST be a mapping"):
        LinkRecord(
            "a",
            "resource-group",
            "contains",
            "b",
            "compute.vm",
            link_props=[],  # type: ignore[arg-type]
        )


def test_legacy_link_record_has_no_observation_metadata() -> None:
    link = LinkRecord("a", "resource-group", "contains", "b", "compute.vm")

    assert link.link_props == {}
    assert link.observation_metadata is None


def test_link_record_rejects_raw_reserved_observation_metadata() -> None:
    with pytest.raises(ValueError, match="reserved observation metadata"):
        LinkRecord(
            "a",
            "resource-group",
            "contains",
            "b",
            "compute.vm",
            link_props={LINK_OBSERVATION_METADATA_PROPERTY: {}},
        )


def test_inventory_batch_final_defaults_to_false() -> None:
    """Callers rely on `final=True` as the atomic-promote fence.

    Defaulting to False forces every adapter to opt in - a stream that
    ends silently must not be treated as complete
    (docs/roadmap/architecture/csp-neutrality.md § 5).
    """
    batch = InventoryBatch()
    assert batch.final is False
    assert batch.resources == ()
    assert batch.links == ()
    assert batch.cursor is None
    assert batch.relationship_reconciliation_after is None


def test_inventory_batch_carries_relationship_reconciliation_marker() -> None:
    batch = InventoryBatch(relationship_reconciliation_after="2026-08-08T01:02:03+00:00")

    assert batch.relationship_reconciliation_after == "2026-08-08T01:02:03+00:00"


@pytest.mark.asyncio
async def test_minimal_async_full_snapshot_streams_final_true() -> None:
    """A trivial async generator implementing the Protocol works end-to-end."""

    class _Fake:
        async def _snap(self) -> AsyncIterator[InventoryBatch]:
            yield InventoryBatch(
                resources=(ResourceRecord(resource_id="rg1", type="resource-group"),),
                cursor="c-0",
                final=False,
            )
            yield InventoryBatch(
                resources=(ResourceRecord(resource_id="vm1", type="compute.vm"),),
                links=(
                    LinkRecord(
                        from_id="rg1",
                        from_type="resource-group",
                        link_type="contains",
                        to_id="vm1",
                        to_type="compute.vm",
                    ),
                ),
                cursor="c-1",
                final=True,
            )

        def full_snapshot(self, since: str | None = None) -> AsyncIterator[InventoryBatch]:
            return self._snap()

        def delta(self, cursor: str) -> AsyncIterator[InventoryBatch]:  # pragma: no cover
            raise NotImplementedError

    fake: Inventory = _Fake()  # type: ignore[assignment]
    seen: list[InventoryBatch] = []
    async for batch in fake.full_snapshot():
        seen.append(batch)
    assert len(seen) == 2
    assert seen[-1].final is True
    assert seen[-1].resources[0].resource_id == "vm1"
