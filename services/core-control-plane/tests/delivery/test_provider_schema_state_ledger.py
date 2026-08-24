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
    manifest = await mirror._store.read_state("provider-schema-ledger:manifest")  # noqa: SLF001
    assert manifest is not None
    assert manifest["revision"] == 1


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

    assert tuple(restored.iterdir()) == ()


async def test_hydration_failure_does_not_publish_a_partial_generation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.json").write_text('{"valid":true}\n', encoding="utf-8")
    (source / "z.json").write_text('{"valid":false}\n', encoding="utf-8")
    store = InMemoryStateStore()
    mirror = StateStoreProviderSchemaLedger(store)
    await mirror.persist(source)
    tampered_digest = "sha256:" + hashlib.sha256(b'{"valid":false}\n').hexdigest()
    await store.write_state(
        f"provider-schema-ledger:blob:{tampered_digest}",
        {"content": "tampered"},
    )
    restored = tmp_path / "restored"
    restored.mkdir()

    with pytest.raises(ProviderSchemaError, match="blob digest mismatch"):
        await mirror.hydrate(restored)

    assert tuple(restored.iterdir()) == ()


async def test_manifest_publish_uses_revision_cas_and_rejects_a_lost_race(
    tmp_path: Path,
) -> None:
    class _LosingStore(InMemoryStateStore):
        lose_next_compare = False

        async def compare_and_set_state_with_audit(
            self,
            key: str,
            value: dict[str, object],
            *,
            expected_revision: int,
            audit_entry: dict[str, object],
        ) -> bool:
            if self.lose_next_compare:
                return False
            return await super().compare_and_set_state_with_audit(
                key,
                value,
                expected_revision=expected_revision,
                audit_entry=audit_entry,
            )

    source = tmp_path / "source"
    source.mkdir()
    (source / "baseline.json").write_text("{}\n", encoding="utf-8")
    store = _LosingStore()
    mirror = StateStoreProviderSchemaLedger(store)
    await mirror.persist(source)
    initial = await store.read_state("provider-schema-ledger:manifest")
    store.lose_next_compare = True

    with pytest.raises(ProviderSchemaError, match="publication conflict"):
        await mirror.persist(source)

    assert await store.read_state("provider-schema-ledger:manifest") == initial


async def test_hydration_rejects_a_replaced_root_before_publication(tmp_path: Path) -> None:
    restored = tmp_path / "restored"
    moved = tmp_path / "restored-moved"

    class _RootReplacingStore(InMemoryStateStore):
        replaced = False

        async def read_state(self, key: str):  # type: ignore[no-untyped-def]
            value = await super().read_state(key)
            if key.startswith("provider-schema-ledger:blob:") and not self.replaced:
                restored.rename(moved)
                restored.mkdir()
                self.replaced = True
            return value

    source = tmp_path / "source"
    source.mkdir()
    (source / "baseline.json").write_text("{}\n", encoding="utf-8")
    store = _RootReplacingStore()
    mirror = StateStoreProviderSchemaLedger(store)
    await mirror.persist(source)
    restored.mkdir()

    with pytest.raises(ProviderSchemaError, match="root changed"):
        await mirror.hydrate(restored)

    assert tuple(restored.iterdir()) == ()
    assert tuple(moved.iterdir()) == ()
