"""Tests for :mod:`fdai.shared.providers.declarative_inventory`."""

from __future__ import annotations

import asyncio
from pathlib import Path
from textwrap import dedent

import pytest
from fdai.shared.providers.declarative_inventory import (
    DeclarativeInventory,
    DeclarativeInventoryConfig,
    DeclarativeInventoryError,
)


def _fixture(tmp_path: Path, text: str, *, suffix: str = ".yaml") -> Path:
    path = tmp_path / f"inv{suffix}"
    path.write_text(dedent(text).lstrip())
    return path


def _config(path: Path) -> DeclarativeInventoryConfig:
    return DeclarativeInventoryConfig(
        fixture_path=path,
        known_resource_types=frozenset({"resource-group", "compute.vm"}),
        known_link_types=frozenset({"contains", "depends_on"}),
    )


def test_config_rejects_non_positive_batch_size(tmp_path: Path) -> None:
    # batch_size is a range() step and a batching bound: 0 raises ValueError
    # mid-iteration; a negative value drops the terminal final=True batch.
    for bad in (0, -1):
        with pytest.raises(DeclarativeInventoryError, match="batch_size"):
            DeclarativeInventoryConfig(
                fixture_path=tmp_path / "inv.yaml",
                known_resource_types=frozenset(),
                known_link_types=frozenset(),
                batch_size=bad,
            )


async def _collect_snapshot(inv: DeclarativeInventory) -> list:
    batches = []
    async for batch in inv.full_snapshot():
        batches.append(batch)
    return batches


def test_load_yaml_fixture_populates_resources_and_links(tmp_path: Path) -> None:
    path = _fixture(
        tmp_path,
        """
        resources:
          - resource_id: rg-a
            type: resource-group
            props: {region: eastus}
          - resource_id: vm-1
            type: compute.vm
            parent_id: rg-a
            props: {tier: S1}
        links:
          - source: rg-a
            target: vm-1
            link_type: contains
        """,
    )
    inv = DeclarativeInventory(_config(path))
    assert inv.resource_count() == 2
    assert inv.link_count() == 1

    batches = asyncio.run(_collect_snapshot(inv))
    all_resources = [r for b in batches for r in b.resources]
    all_links = [link for b in batches for link in b.links]
    assert {r.resource_id for r in all_resources} == {"rg-a", "vm-1"}
    assert all_links[0].from_id == "rg-a"
    assert all_links[0].to_id == "vm-1"
    assert all_links[0].from_type == "resource-group"
    assert all_links[0].to_type == "compute.vm"
    # Terminal batch MUST carry final=True.
    assert batches[-1].final is True


def test_load_json_fixture_works(tmp_path: Path) -> None:
    path = _fixture(
        tmp_path,
        '{"resources": [{"resource_id": "rg-a", "type": "resource-group"}], "links": []}',
        suffix=".json",
    )
    inv = DeclarativeInventory(_config(path))
    assert inv.resource_count() == 1


def test_rejects_unknown_resource_type(tmp_path: Path) -> None:
    path = _fixture(
        tmp_path,
        """
        resources:
          - resource_id: x
            type: not-registered
        links: []
        """,
    )
    with pytest.raises(DeclarativeInventoryError, match="not in registered resource-types"):
        DeclarativeInventory(_config(path))


def test_rejects_unknown_link_type(tmp_path: Path) -> None:
    path = _fixture(
        tmp_path,
        """
        resources:
          - resource_id: a
            type: resource-group
          - resource_id: b
            type: compute.vm
        links:
          - source: a
            target: b
            link_type: not-a-link
        """,
    )
    with pytest.raises(DeclarativeInventoryError, match="not in registered link-types"):
        DeclarativeInventory(_config(path))


def test_rejects_duplicate_resource_id(tmp_path: Path) -> None:
    path = _fixture(
        tmp_path,
        """
        resources:
          - resource_id: x
            type: resource-group
          - resource_id: x
            type: compute.vm
        links: []
        """,
    )
    with pytest.raises(DeclarativeInventoryError, match="duplicates resource_id"):
        DeclarativeInventory(_config(path))


def test_rejects_dangling_link_endpoint(tmp_path: Path) -> None:
    path = _fixture(
        tmp_path,
        """
        resources:
          - resource_id: a
            type: resource-group
        links:
          - source: a
            target: ghost
            link_type: contains
        """,
    )
    with pytest.raises(DeclarativeInventoryError, match="references unknown resource_id"):
        DeclarativeInventory(_config(path))


def test_empty_fixture_still_emits_terminal_batch(tmp_path: Path) -> None:
    path = _fixture(tmp_path, "resources: []\nlinks: []\n")
    inv = DeclarativeInventory(_config(path))
    batches = asyncio.run(_collect_snapshot(inv))
    assert len(batches) == 1
    assert batches[0].final is True


def test_delta_returns_empty_batch(tmp_path: Path) -> None:
    path = _fixture(tmp_path, "resources: []\nlinks: []\n")
    inv = DeclarativeInventory(_config(path))

    async def _collect() -> list:
        batches = []
        async for batch in inv.delta("cursor-x"):
            batches.append(batch)
        return batches

    batches = asyncio.run(_collect())
    assert len(batches) == 1
    assert batches[0].final is True
    assert batches[0].resources == ()
    assert batches[0].links == ()


def test_parent_id_lands_in_props_when_provided(tmp_path: Path) -> None:
    path = _fixture(
        tmp_path,
        """
        resources:
          - resource_id: rg-a
            type: resource-group
          - resource_id: vm-1
            type: compute.vm
            parent_id: rg-a
        links: []
        """,
    )
    inv = DeclarativeInventory(_config(path))
    batches = asyncio.run(_collect_snapshot(inv))
    vm_records = [r for b in batches for r in b.resources if r.resource_id == "vm-1"]
    assert vm_records[0].props["parent_id"] == "rg-a"
