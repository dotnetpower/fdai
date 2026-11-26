"""Tests for the state-store-backed remediation-pack registry."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.security.code_findings.result_import import PackRecord
from fdai.delivery.code_security_registry import FileRemediationPackRegistry
from fdai.delivery.persistence.state_store_code_security_registry import (
    BASELINE_STATE_PREFIX,
    PACK_STATE_PREFIX,
    STATE_STORE_REGISTRY,
    StateStoreRemediationPackRegistry,
    open_pack_registry,
)
from fdai.shared.providers.remediation_pack import PackRegistryError, RemediationPackRegistry
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 10, 7, tzinfo=UTC)


def _pack(pack_id: str = "0123456789ab", *, days: int = 7) -> PackRecord:
    return PackRecord(
        pack_id=pack_id,
        manifest_sha256="1" * 64,
        base_commit="a" * 40,
        issue_ids=frozenset({"FDAI-SEC-0123456789ab"}),
        expires_at=_NOW + timedelta(days=days),
    )


def _registry(store: InMemoryStateStore | None = None) -> StateStoreRemediationPackRegistry:
    return StateStoreRemediationPackRegistry(store or InMemoryStateStore(), clock=lambda: _NOW)


async def test_registry_satisfies_the_protocol_and_round_trips() -> None:
    registry = _registry()
    assert isinstance(registry, RemediationPackRegistry)
    await registry.record(_pack())
    assert await registry.get("0123456789ab") == _pack()
    assert await registry.get("ffffffffffff") is None
    with pytest.raises(PackRegistryError, match="already recorded"):
        await registry.record(_pack())


async def test_revocation_and_active_listing() -> None:
    registry = _registry()
    await registry.record(_pack("0123456789ab"))
    await registry.record(_pack("ba9876543210"))
    await registry.record(_pack("aaaaaaaaaaaa", days=-1))
    revoked = await registry.revoke("ba9876543210", "rotated key")
    assert revoked.revoked is True
    assert [p.pack_id for p in await registry.list_active()] == ["0123456789ab"]
    with pytest.raises(PackRegistryError, match="not recorded"):
        await registry.revoke("ffffffffffff", "unknown")


async def test_baseline_is_separate_and_write_once() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    await registry.record(_pack())
    await registry.record_baseline("0123456789ab", {"issues": [{"path": "src/app.py"}]})
    assert await registry.get_baseline("0123456789ab") == {"issues": [{"path": "src/app.py"}]}
    pack_row = await store.read_state(PACK_STATE_PREFIX + "0123456789ab")
    assert pack_row is not None and "issues" not in pack_row
    assert await store.read_state(BASELINE_STATE_PREFIX + "0123456789ab") is not None
    with pytest.raises(PackRegistryError, match="already has a baseline"):
        await registry.record_baseline("0123456789ab", {})


async def test_concurrent_reviews_are_all_kept_in_order() -> None:
    registry = _registry()
    await registry.record(_pack())
    await asyncio.gather(
        *(registry.append_review("0123456789ab", {"kind": "note", "n": n}) for n in range(5))
    )
    reviews = await registry.list_reviews("0123456789ab")
    assert sorted(item["n"] for item in reviews) == [0, 1, 2, 3, 4]
    assert all(item["recorded_at"] == _NOW.isoformat() for item in reviews)
    with pytest.raises(PackRegistryError, match="not recorded"):
        await registry.append_review("ffffffffffff", {"kind": "note"})


async def test_invalid_pack_id_is_rejected() -> None:
    with pytest.raises(PackRegistryError, match="12 lowercase hex"):
        await _registry().get("../escape")


def test_factory_selects_file_or_state_store(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert isinstance(open_pack_registry(str(tmp_path)), FileRemediationPackRegistry)
    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)
    monkeypatch.delenv("FDAI_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="FDAI_STATE_STORE_DSN"):
        open_pack_registry(STATE_STORE_REGISTRY)
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://example.invalid/fdai")
    assert isinstance(open_pack_registry(STATE_STORE_REGISTRY), StateStoreRemediationPackRegistry)
