"""Local provider implementations - dev-mode parity."""

from __future__ import annotations

from pathlib import Path

import pytest

from aiopspilot.shared.providers.inventory import Inventory
from aiopspilot.shared.providers.local import (
    EnvSecretProvider,
    FileFixtureInventory,
    LocalWorkloadIdentity,
    LocalWorkloadIdentityConfig,
)
from aiopspilot.shared.providers.local.inventory import (
    InventoryFixtureError,
    load_inventory_fixture,
)
from aiopspilot.shared.providers.secret_provider import (
    SecretNotFoundError,
    SecretProvider,
)
from aiopspilot.shared.providers.workload_identity import WorkloadIdentity

# ---------------------------------------------------------------------------
# EnvSecretProvider
# ---------------------------------------------------------------------------


def test_env_secret_provider_satisfies_protocol() -> None:
    provider: SecretProvider = EnvSecretProvider(env={"AIOPSPILOT_SECRET_KAFKA_TOKEN": "abc"})
    assert isinstance(provider, SecretProvider)


@pytest.mark.asyncio
async def test_env_secret_provider_returns_prefixed_value() -> None:
    provider = EnvSecretProvider(env={"AIOPSPILOT_SECRET_KAFKA_TOKEN": "abc"})
    assert await provider.get("kafka-token") == "abc"


@pytest.mark.asyncio
async def test_env_secret_provider_falls_through_to_bare_key() -> None:
    provider = EnvSecretProvider(env={"kafka-token": "raw"})
    assert await provider.get("kafka-token") == "raw"


@pytest.mark.asyncio
async def test_env_secret_provider_raises_when_missing() -> None:
    provider = EnvSecretProvider(env={})
    with pytest.raises(SecretNotFoundError):
        await provider.get("nope")


# ---------------------------------------------------------------------------
# LocalWorkloadIdentity
# ---------------------------------------------------------------------------


def test_local_workload_identity_satisfies_protocol() -> None:
    identity: WorkloadIdentity = LocalWorkloadIdentity()
    assert isinstance(identity, WorkloadIdentity)


@pytest.mark.asyncio
async def test_local_workload_identity_returns_stable_token_per_audience() -> None:
    identity = LocalWorkloadIdentity()
    a = await identity.get_token("https://cognitiveservices.azure.com/.default")
    b = await identity.get_token("https://cognitiveservices.azure.com/.default")
    assert a.token == b.token
    assert a.token.startswith("aiopspilot-local:")


@pytest.mark.asyncio
async def test_local_workload_identity_isolates_audiences() -> None:
    identity = LocalWorkloadIdentity()
    a = await identity.get_token("aud-1")
    b = await identity.get_token("aud-2")
    assert a.token != b.token
    assert a.audience == "aud-1"
    assert b.audience == "aud-2"


def test_local_workload_identity_rejects_zero_ttl() -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        LocalWorkloadIdentity(config=LocalWorkloadIdentityConfig(ttl_seconds=0))


# ---------------------------------------------------------------------------
# FileFixtureInventory
# ---------------------------------------------------------------------------


_FIXTURE = """
resources:
  - resource_id: "resource:example/rg/a"
    type: object-storage
    props:
      public_access: true
    provider_ref: "/subs/x/rg/y/providers/z/a"
    last_seen: "2026-07-05T00:00:00Z"
  - resource_id: "resource:example/rg/b"
    type: compute-vm-scale-set
    props:
      instance_count: 3
links:
  - from_id: "resource:example/rg/a"
    from_type: object-storage
    link_type: contains
    to_id: "resource:example/rg/b"
    to_type: compute-vm-scale-set
"""


def test_file_fixture_inventory_satisfies_protocol(tmp_path: Path) -> None:
    p = tmp_path / "inv.yaml"
    p.write_text(_FIXTURE, encoding="utf-8")
    inv: Inventory = FileFixtureInventory(fixture=p)
    assert isinstance(inv, Inventory)


@pytest.mark.asyncio
async def test_file_fixture_inventory_emits_one_final_batch(tmp_path: Path) -> None:
    p = tmp_path / "inv.yaml"
    p.write_text(_FIXTURE, encoding="utf-8")
    inv = FileFixtureInventory(fixture=p)
    batches = [b async for b in inv.full_snapshot()]
    assert len(batches) == 1
    batch = batches[0]
    assert batch.final is True
    assert batch.cursor == "fixture"
    assert len(batch.resources) == 2
    assert batch.resources[0].resource_id == "resource:example/rg/a"
    assert batch.resources[0].props == {"public_access": True}
    assert len(batch.links) == 1
    assert batch.links[0].link_type == "contains"


@pytest.mark.asyncio
async def test_file_fixture_inventory_delta_is_empty_stream(tmp_path: Path) -> None:
    p = tmp_path / "inv.yaml"
    p.write_text(_FIXTURE, encoding="utf-8")
    inv = FileFixtureInventory(fixture=p)
    batches = [b async for b in inv.delta(cursor="fixture")]
    assert batches == []


def test_file_fixture_inventory_rejects_non_mapping_root(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("- item\n", encoding="utf-8")
    with pytest.raises(InventoryFixtureError, match="mapping"):
        FileFixtureInventory(fixture=p)


def test_file_fixture_inventory_rejects_missing_resource_field(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(
        "resources:\n  - type: object-storage\n",
        encoding="utf-8",
    )
    with pytest.raises(InventoryFixtureError, match="resource_id"):
        FileFixtureInventory(fixture=p)


def test_file_fixture_inventory_rejects_missing_link_field(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(
        "links:\n"
        "  - from_id: a\n"
        "    from_type: object-storage\n"
        "    link_type: contains\n"
        "    to_id: b\n",
        encoding="utf-8",
    )
    with pytest.raises(InventoryFixtureError, match="to_type"):
        FileFixtureInventory(fixture=p)


def test_load_inventory_fixture_accepts_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    resources, links = load_inventory_fixture(p)
    assert resources == ()
    assert links == ()


def test_file_fixture_inventory_rejects_resources_not_a_list(tmp_path: Path) -> None:
    """`resources:` MUST be a YAML list, not a mapping/scalar."""
    p = tmp_path / "bad.yaml"
    p.write_text("resources: {}\n", encoding="utf-8")
    with pytest.raises(InventoryFixtureError, match="'resources' MUST be a list"):
        FileFixtureInventory(fixture=p)


def test_file_fixture_inventory_rejects_resource_entry_not_a_mapping(tmp_path: Path) -> None:
    """Each `resources[i]` entry MUST be a mapping."""
    p = tmp_path / "bad.yaml"
    p.write_text("resources:\n  - just-a-string\n", encoding="utf-8")
    with pytest.raises(InventoryFixtureError, match=r"resources\[0\] MUST be a mapping"):
        FileFixtureInventory(fixture=p)


def test_file_fixture_inventory_rejects_links_not_a_list(tmp_path: Path) -> None:
    """`links:` MUST be a YAML list."""
    p = tmp_path / "bad.yaml"
    p.write_text("links: {}\n", encoding="utf-8")
    with pytest.raises(InventoryFixtureError, match="'links' MUST be a list"):
        FileFixtureInventory(fixture=p)


def test_file_fixture_inventory_rejects_link_entry_not_a_mapping(tmp_path: Path) -> None:
    """Each `links[i]` entry MUST be a mapping."""
    p = tmp_path / "bad.yaml"
    p.write_text("links:\n  - just-a-string\n", encoding="utf-8")
    with pytest.raises(InventoryFixtureError, match=r"links\[0\] MUST be a mapping"):
        FileFixtureInventory(fixture=p)
