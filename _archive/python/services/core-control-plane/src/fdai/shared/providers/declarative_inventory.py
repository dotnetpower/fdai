"""Declarative static-file :class:`Inventory` adapter.

Reads a JSON / YAML fixture file describing a resource inventory and
serves it via the same :class:`~fdai.shared.providers.inventory.Inventory`
contract the Azure Resource Graph adapter satisfies. Purpose:

- **Air-gapped / offline** deployments (no cloud API access) get a
  working inventory without wiring a live adapter.
- **Fork authors** validate new ObjectType + LinkType graphs against a
  hand-authored fixture before spinning up cloud infrastructure.
- **Dev harness** loads a small snapshot instantly so the console has
  something to render out of the box.

File format (YAML or JSON; auto-detected by extension)::

    resources:
      - resource_id: rg-alpha
        type: resource-group
        props: {region: eastus}
      - resource_id: vm-1
        type: compute.vm
        parent_id: rg-alpha
        props: {tier: S1}
    links:
      - source: rg-alpha
        target: vm-1
        link_type: contains

Every entry is validated against the shipped ontology's
``resource-types.yaml`` + ``link-types/`` catalog; unknown types
fail-close so a typo cannot silently pollute the graph.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fdai.shared.providers.inventory import InventoryBatch, LinkRecord, ResourceRecord


class DeclarativeInventoryError(ValueError):
    """Raised when the fixture file fails validation."""


@dataclass(frozen=True, slots=True)
class DeclarativeInventoryConfig:
    """Composition-root config for :class:`DeclarativeInventory`."""

    fixture_path: Path
    known_resource_types: frozenset[str]
    known_link_types: frozenset[str]
    batch_size: int = 200

    def __post_init__(self) -> None:
        # batch_size is a ``range`` step and a batching bound: 0 raises
        # ValueError mid-iteration and a negative value emits no final
        # (terminal) batch, so a consumer keyed on ``final`` never completes.
        if self.batch_size < 1:
            raise DeclarativeInventoryError("batch_size MUST be >= 1")


class DeclarativeInventory:
    """Static-file :class:`~fdai.shared.providers.inventory.Inventory`.

    Loads the fixture eagerly at construction so ``full_snapshot`` and
    ``delta`` are pure in-memory iteration (no disk I/O per call).
    ``delta`` returns an empty batch (marker) - static fixtures do not
    change; a fork wanting mutation semantics ships a different adapter.
    """

    def __init__(self, config: DeclarativeInventoryConfig) -> None:
        self._config = config
        self._resources, self._links = _load_fixture(
            config.fixture_path,
            known_resource_types=config.known_resource_types,
            known_link_types=config.known_link_types,
        )

    def full_snapshot(self, since: str | None = None) -> AsyncIterator[InventoryBatch]:
        del since  # static fixture ignores the delta-hint on full pulls
        return self._iter_snapshot()

    def delta(self, cursor: str) -> AsyncIterator[InventoryBatch]:
        del cursor  # static fixture has no delta stream
        return self._iter_empty()

    def resource_count(self) -> int:
        return len(self._resources)

    def link_count(self) -> int:
        return len(self._links)

    # ------------------------------------------------------------------
    # AsyncIterator implementations
    # ------------------------------------------------------------------

    async def _iter_snapshot(self) -> AsyncIterator[InventoryBatch]:
        batches = list(_batched(self._resources, self._config.batch_size))
        link_batches = list(_batched(self._links, self._config.batch_size))
        total = max(1, len(batches) + len(link_batches))
        emitted = 0
        for resource_batch in batches:
            emitted += 1
            yield InventoryBatch(
                resources=tuple(resource_batch),
                links=(),
                cursor=f"decl:snap:{emitted}",
                final=emitted == total,
            )
        for link_batch in link_batches:
            emitted += 1
            yield InventoryBatch(
                resources=(),
                links=tuple(link_batch),
                cursor=f"decl:snap:{emitted}",
                final=emitted == total,
            )
        if not self._resources and not self._links:
            # Empty fixture still MUST emit one terminal batch so the
            # consumer knows the pull finished.
            yield InventoryBatch(resources=(), links=(), cursor="decl:snap:0", final=True)

    async def _iter_empty(self) -> AsyncIterator[InventoryBatch]:
        yield InventoryBatch(resources=(), links=(), cursor="decl:delta:0", final=True)


# ---------------------------------------------------------------------------
# Loader helpers
# ---------------------------------------------------------------------------


def _load_fixture(
    path: Path,
    *,
    known_resource_types: frozenset[str],
    known_link_types: frozenset[str],
) -> tuple[list[ResourceRecord], list[LinkRecord]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        raw: Any = json.loads(text)
    else:
        raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise DeclarativeInventoryError("fixture top-level MUST be a mapping")

    resources_raw = raw.get("resources", [])
    links_raw = raw.get("links", [])
    if not isinstance(resources_raw, list) or not isinstance(links_raw, list):
        raise DeclarativeInventoryError("'resources' and 'links' MUST be lists")

    seen_ids: set[str] = set()
    resource_types_by_id: dict[str, str] = {}
    resources: list[ResourceRecord] = []
    for idx, entry in enumerate(resources_raw):
        if not isinstance(entry, dict):
            raise DeclarativeInventoryError(f"resources[{idx}] MUST be a mapping")
        resource_id = entry.get("resource_id")
        resource_type = entry.get("type")
        props = entry.get("props") or {}
        parent_id = entry.get("parent_id")
        if not isinstance(resource_id, str) or not resource_id:
            raise DeclarativeInventoryError(f"resources[{idx}].resource_id required")
        if not isinstance(resource_type, str) or not resource_type:
            raise DeclarativeInventoryError(f"resources[{idx}].type required")
        if resource_type not in known_resource_types:
            raise DeclarativeInventoryError(
                f"resources[{idx}].type {resource_type!r} not in registered resource-types"
            )
        if resource_id in seen_ids:
            raise DeclarativeInventoryError(
                f"resources[{idx}] duplicates resource_id {resource_id!r}"
            )
        if not isinstance(props, dict):
            raise DeclarativeInventoryError(f"resources[{idx}].props MUST be a mapping")
        if parent_id is not None and not isinstance(parent_id, str):
            raise DeclarativeInventoryError(f"resources[{idx}].parent_id MUST be a string")
        seen_ids.add(resource_id)
        resource_types_by_id[resource_id] = resource_type
        merged_props = dict(props)
        if parent_id is not None:
            merged_props.setdefault("parent_id", parent_id)
        resources.append(
            ResourceRecord(
                resource_id=resource_id,
                type=resource_type,
                props=merged_props,
            )
        )

    links: list[LinkRecord] = []
    for idx, entry in enumerate(links_raw):
        if not isinstance(entry, dict):
            raise DeclarativeInventoryError(f"links[{idx}] MUST be a mapping")
        source = entry.get("source")
        target = entry.get("target")
        link_type = entry.get("link_type")
        if not isinstance(source, str) or not source:
            raise DeclarativeInventoryError(f"links[{idx}].source required")
        if not isinstance(target, str) or not target:
            raise DeclarativeInventoryError(f"links[{idx}].target required")
        if not isinstance(link_type, str) or not link_type:
            raise DeclarativeInventoryError(f"links[{idx}].link_type required")
        if link_type not in known_link_types:
            raise DeclarativeInventoryError(
                f"links[{idx}].link_type {link_type!r} not in registered link-types"
            )
        if source not in seen_ids or target not in seen_ids:
            raise DeclarativeInventoryError(
                f"links[{idx}] references unknown resource_id "
                f"(source={source!r}, target={target!r})"
            )
        links.append(
            LinkRecord(
                from_id=source,
                from_type=resource_types_by_id[source],
                link_type=link_type,
                to_id=target,
                to_type=resource_types_by_id[target],
            )
        )

    return resources, links


def _batched(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


__all__ = [
    "DeclarativeInventory",
    "DeclarativeInventoryConfig",
    "DeclarativeInventoryError",
]
