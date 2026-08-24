"""Durable StateStore mirror checks for the provider-schema ledger."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fdai.delivery.provider_schema import ProviderSchemaError
from fdai.delivery.provider_schema_state_ledger import StateStoreProviderSchemaLedger
from fdai.shared.providers.testing.state_store import InMemoryStateStore


async def test_persists_and_hydrates_one_complete_generation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "azure" / "snapshots").mkdir(parents=True)
    (source / "azure" / "baseline.json").write_text('{"digest":"a"}\n', encoding="utf-8")
    (source / "azure" / "snapshots" / "a.json").write_text(
        '{"snapshot":true}\n',
        encoding="utf-8",
    )
    mirror = StateStoreProviderSchemaLedger(InMemoryStateStore())

    generation_digest = await mirror.persist(source)
    restored = tmp_path / "restored"
    restored.mkdir()

    assert await mirror.hydrate(restored) is True
    assert generation_digest.startswith("sha256:")
    assert (restored / "azure" / "baseline.json").read_bytes() == (
        source / "azure" / "baseline.json"
    ).read_bytes()
    assert (restored / "azure" / "snapshots" / "a.json").read_bytes() == (
        source / "azure" / "snapshots" / "a.json"
    ).read_bytes()


async def test_empty_store_has_no_generation(tmp_path: Path) -> None:
    assert await StateStoreProviderSchemaLedger(InMemoryStateStore()).hydrate(tmp_path) is False


async def test_hydration_rejects_tampered_blob(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "baseline.json").write_text("{}\n", encoding="utf-8")
    store = InMemoryStateStore()
    mirror = StateStoreProviderSchemaLedger(store)
    await mirror.persist(source)
    blob = "provider-schema-ledger:blob:sha256:" + hashlib.sha256(b"{}\n").hexdigest()
    await store.write_state(blob, {"content": "tampered"})
    restored = tmp_path / "restored"
    restored.mkdir()

    with pytest.raises(ProviderSchemaError, match="blob digest mismatch"):
        await mirror.hydrate(restored)
