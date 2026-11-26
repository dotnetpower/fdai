"""FileFixtureInventory - YAML-backed Inventory for dev + tests.

Realizes :class:`~fdai.shared.providers.inventory.Inventory` by
streaming a single fixture file as one final :class:`InventoryBatch`.
Delta is a no-op stream (returns immediately) because a static fixture
has nothing to delta against - a test that needs an incremental stream
supplies its own Inventory fake.

Fixture shape (YAML)::

    resources:
      - resource_id: "resource:example/rg/x"
        type: object-storage
        props: {public_access: true}
        provider_ref: "/subs/.../rg/.../providers/..."
        last_seen: "2026-07-05T00:00:00Z"
    links:
      - from_id: "resource:example/rg/x"
        from_type: object-storage
        link_type: contains
        to_id: "resource:example/rg/y"
        to_type: object-storage
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import yaml

from fdai.shared.providers.inventory import (
    InventoryBatch,
    LinkRecord,
    ResourceRecord,
)


class InventoryFixtureError(ValueError):
    """Raised when the YAML fixture is malformed."""


def load_inventory_fixture(
    path: Path,
) -> tuple[tuple[ResourceRecord, ...], tuple[LinkRecord, ...]]:
    """Parse a YAML fixture into typed records.

    Raises :class:`InventoryFixtureError` on any structural problem so
    the fixture is validated once at load time and not lazily on
    iteration.
    """
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise InventoryFixtureError(f"fixture {path} MUST be a YAML mapping")

    resources = _parse_resources(raw.get("resources", []))
    links = _parse_links(raw.get("links", []))
    return resources, links


def _parse_resources(raw: Any) -> tuple[ResourceRecord, ...]:
    if not isinstance(raw, list):
        raise InventoryFixtureError("'resources' MUST be a list")
    out: list[ResourceRecord] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise InventoryFixtureError(f"resources[{i}] MUST be a mapping")
        try:
            record = ResourceRecord(
                resource_id=str(entry["resource_id"]),
                type=str(entry["type"]),
                props=dict(entry.get("props") or {}),
                provider_ref=entry.get("provider_ref"),
                last_seen=entry.get("last_seen"),
            )
        except KeyError as exc:
            raise InventoryFixtureError(
                f"resources[{i}] missing required field: {exc.args[0]!r}"
            ) from exc
        out.append(record)
    return tuple(out)


def _parse_links(raw: Any) -> tuple[LinkRecord, ...]:
    if not isinstance(raw, list):
        raise InventoryFixtureError("'links' MUST be a list")
    out: list[LinkRecord] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise InventoryFixtureError(f"links[{i}] MUST be a mapping")
        try:
            record = LinkRecord(
                from_id=str(entry["from_id"]),
                from_type=str(entry["from_type"]),
                link_type=str(entry["link_type"]),
                to_id=str(entry["to_id"]),
                to_type=str(entry["to_type"]),
                link_props=dict(entry.get("link_props") or {}),
            )
        except KeyError as exc:
            raise InventoryFixtureError(
                f"links[{i}] missing required field: {exc.args[0]!r}"
            ) from exc
        out.append(record)
    return tuple(out)


class FileFixtureInventory:
    """Dev :class:`Inventory` returning a single final batch."""

    def __init__(self, *, fixture: Path) -> None:
        self._fixture = fixture
        self._resources, self._links = load_inventory_fixture(fixture)

    def full_snapshot(self, since: str | None = None) -> AsyncIterator[InventoryBatch]:
        del since  # fixture is static - no incremental slicing.
        return self._emit_once(cursor="fixture", final=True)

    def delta(self, cursor: str) -> AsyncIterator[InventoryBatch]:
        del cursor  # static fixture has nothing to delta.
        return self._empty()

    async def _emit_once(self, *, cursor: str, final: bool) -> AsyncIterator[InventoryBatch]:
        yield InventoryBatch(
            resources=self._resources,
            links=self._links,
            cursor=cursor,
            final=final,
        )

    async def _empty(self) -> AsyncIterator[InventoryBatch]:
        # Yield nothing - a no-op delta stream.
        if False:  # pragma: no cover - required so the function is an async generator
            yield InventoryBatch()


__all__ = [
    "FileFixtureInventory",
    "InventoryFixtureError",
    "load_inventory_fixture",
]
