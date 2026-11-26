"""Durable snapshot mirror - fake store, no Azure dependency."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fdai.rule_catalog.pipeline.snapshot_mirror import SnapshotMirror, SnapshotMirrorReceipt


class _FakeStore:
    def __init__(self) -> None:
        self.written: dict[str, bytes] = {}
        self.put_calls = 0

    async def put(self, storage_ref: str, content: bytes, *, digest: str) -> bool:
        self.put_calls += 1
        assert hashlib.sha256(content).hexdigest() == digest
        if storage_ref in self.written:
            return False
        self.written[storage_ref] = content
        return True


def _write_tree(root: Path) -> None:
    (root / "a.yaml").write_text("a: 1\n", encoding="utf-8")
    nested = root / "nested"
    nested.mkdir()
    (nested / "b.yaml").write_text("b: 2\n", encoding="utf-8")


async def test_mirror_writes_every_file_content_addressed(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    store = _FakeStore()
    mirror = SnapshotMirror(store=store)

    receipt = await mirror.mirror(
        source_id="example-source", resolved_revision="0" * 40, snapshot_dir=tmp_path
    )

    assert isinstance(receipt, SnapshotMirrorReceipt)
    assert [file.relative_path for file in receipt.files] == ["a.yaml", "nested/b.yaml"]
    assert all(file.newly_written for file in receipt.files)
    assert store.put_calls == 2
    for file in receipt.files:
        expected_ref = f"rule-catalog-snapshots/example-source/{'0' * 40}/{file.relative_path}"
        assert file.storage_ref == expected_ref


async def test_mirror_is_replayable_against_unchanged_content(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    store = _FakeStore()
    mirror = SnapshotMirror(store=store)

    first = await mirror.mirror(
        source_id="example-source", resolved_revision="0" * 40, snapshot_dir=tmp_path
    )
    second = await mirror.mirror(
        source_id="example-source", resolved_revision="0" * 40, snapshot_dir=tmp_path
    )

    assert first.tree_sha256 == second.tree_sha256
    assert all(not file.newly_written for file in second.files)
    assert store.put_calls == 4


async def test_mirror_rejects_missing_directory(tmp_path: Path) -> None:
    store = _FakeStore()
    mirror = SnapshotMirror(store=store)

    with pytest.raises(ValueError, match="does not exist"):
        await mirror.mirror(
            source_id="example-source",
            resolved_revision="0" * 40,
            snapshot_dir=tmp_path / "absent",
        )


async def test_mirror_rejects_empty_identifiers(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    mirror = SnapshotMirror(store=_FakeStore())

    with pytest.raises(ValueError, match="non-empty source id"):
        await mirror.mirror(source_id="", resolved_revision="0" * 40, snapshot_dir=tmp_path)


def test_storage_prefix_must_be_a_safe_segment() -> None:
    with pytest.raises(ValueError, match="safe lowercase segment"):
        SnapshotMirror(store=_FakeStore(), storage_prefix="Not Safe/../x")


async def test_oversized_file_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "big.bin").write_bytes(b"0" * (8 * 1024 * 1024 + 1))
    mirror = SnapshotMirror(store=_FakeStore())

    with pytest.raises(ValueError, match="outside the allowed range"):
        await mirror.mirror(
            source_id="example-source", resolved_revision="0" * 40, snapshot_dir=tmp_path
        )
