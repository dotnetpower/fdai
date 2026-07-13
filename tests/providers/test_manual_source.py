"""Tests for the manual-source ingestion seam (contracts + drop-directory adapter)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fdai.shared.providers.distiller import ManualDocument
from fdai.shared.providers.manual_source import (
    DropDirectoryManualSource,
    EmptyManualSource,
    ManualCandidate,
    ManualChangeType,
    ManualSource,
)

# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


def test_candidate_rejects_empty_identity() -> None:
    with pytest.raises(ValueError, match="doc_id"):
        ManualCandidate(doc_id="", source_ref="drop://x")
    with pytest.raises(ValueError, match="source_ref"):
        ManualCandidate(doc_id="x", source_ref="")


def test_candidate_rejects_negative_signals() -> None:
    with pytest.raises(ValueError, match="view_count"):
        ManualCandidate(doc_id="x", source_ref="drop://x", view_count=-1)
    with pytest.raises(ValueError, match="inbound_links"):
        ManualCandidate(doc_id="x", source_ref="drop://x", inbound_links=-1)


def test_empty_and_drop_satisfy_protocol(tmp_path: Path) -> None:
    assert isinstance(EmptyManualSource(), ManualSource)
    assert isinstance(DropDirectoryManualSource(tmp_path), ManualSource)


# ---------------------------------------------------------------------------
# EmptyManualSource (fail-safe default)
# ---------------------------------------------------------------------------


async def test_empty_source_offers_nothing() -> None:
    source = EmptyManualSource()
    assert await source.list_candidates() == ()
    assert await source.fetch("anything") is None
    assert await source.changes("2026-01-01T00:00:00Z") == ()


# ---------------------------------------------------------------------------
# DropDirectoryManualSource
# ---------------------------------------------------------------------------


async def test_drop_lists_and_fetches_text_file(tmp_path: Path) -> None:
    (tmp_path / "runbook.md").write_text("# Restart\nRestart the pod.\n", encoding="utf-8")
    source = DropDirectoryManualSource(tmp_path)

    candidates = await source.list_candidates()
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.doc_id == "runbook.md"
    assert cand.source_ref == "drop://runbook.md"
    assert cand.title == "runbook.md"
    assert cand.content_sha  # non-empty sha

    doc = await source.fetch("runbook.md")
    assert isinstance(doc, ManualDocument)
    assert "Restart the pod." in doc.text
    assert doc.source_ref == "drop://runbook.md"
    assert doc.content_sha == cand.content_sha
    assert "decode" not in doc.metadata


async def test_drop_list_is_deterministic_and_recursive(tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text("b", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.md").write_text("a", encoding="utf-8")
    source = DropDirectoryManualSource(tmp_path)

    ids = [c.doc_id for c in await source.list_candidates()]
    assert ids == ["b.md", "sub/a.md"]  # sorted, posix-relative, recursive


async def test_drop_missing_directory_is_empty(tmp_path: Path) -> None:
    source = DropDirectoryManualSource(tmp_path / "does-not-exist")
    assert await source.list_candidates() == ()


async def test_drop_fetch_unknown_returns_none(tmp_path: Path) -> None:
    source = DropDirectoryManualSource(tmp_path)
    assert await source.fetch("nope.md") is None


async def test_drop_fetch_rejects_path_traversal(tmp_path: Path) -> None:
    (tmp_path.parent / "secret.md").write_text("secret", encoding="utf-8")
    source = DropDirectoryManualSource(tmp_path)
    assert await source.fetch("../secret.md") is None


async def test_drop_lists_ignore_symlink_escaping_root(tmp_path: Path) -> None:
    import os

    root = tmp_path / "drop"
    root.mkdir()
    (root / "real.md").write_text("real manual", encoding="utf-8")
    outside = tmp_path / "outside-secret.md"
    outside.write_text("secret outside the drop root", encoding="utf-8")
    os.symlink(outside, root / "link.md")  # dropped symlink escaping root

    source = DropDirectoryManualSource(root)
    # Listing must not crash and must exclude the escaping symlink.
    ids = [c.doc_id for c in await source.list_candidates()]
    assert ids == ["real.md"]
    # fetch through the symlink also refuses (resolved path escapes root).
    assert await source.fetch("link.md") is None


async def test_drop_fetch_rejects_symlink_to_outside(tmp_path: Path) -> None:
    import os

    root = tmp_path / "drop"
    root.mkdir()
    outside = tmp_path / "target.md"
    outside.write_text("outside", encoding="utf-8")
    os.symlink(outside, root / "escape.md")
    source = DropDirectoryManualSource(root)
    assert await source.fetch("escape.md") is None


async def test_drop_skips_oversize_files(tmp_path: Path) -> None:
    small = tmp_path / "small.md"
    small.write_text("tiny manual", encoding="utf-8")
    big = tmp_path / "big.md"
    big.write_text("x" * 200, encoding="utf-8")
    source = DropDirectoryManualSource(tmp_path, max_bytes=100)

    ids = [c.doc_id for c in await source.list_candidates()]
    assert ids == ["small.md"]  # oversize file excluded from listing
    assert await source.fetch("small.md") is not None
    assert await source.fetch("big.md") is None  # oversize refused on fetch too


def test_drop_rejects_non_positive_max_bytes(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        DropDirectoryManualSource(tmp_path, max_bytes=0)


async def test_drop_flags_lossy_decode(tmp_path: Path) -> None:
    (tmp_path / "binary.bin").write_bytes(b"\xff\xfe\x00bad utf8")
    source = DropDirectoryManualSource(tmp_path)
    doc = await source.fetch("binary.bin")
    assert doc is not None
    assert doc.metadata.get("decode") == "lossy"


async def test_drop_changes_reports_upserts_after_cutoff(tmp_path: Path) -> None:
    import os
    import time

    old = tmp_path / "old.md"
    old.write_text("old", encoding="utf-8")
    old_ts = time.time() - 3600
    os.utime(old, (old_ts, old_ts))

    new = tmp_path / "new.md"
    new.write_text("new", encoding="utf-8")

    source = DropDirectoryManualSource(tmp_path)
    from fdai.shared.providers.manual_source import _iso_utc

    cutoff = _iso_utc(time.time() - 60)
    changes = await source.changes(cutoff)
    assert [c.candidate.doc_id for c in changes] == ["new.md"]
    assert changes[0].change_type is ManualChangeType.UPSERTED


async def test_drop_changes_rejects_bad_cursor(tmp_path: Path) -> None:
    source = DropDirectoryManualSource(tmp_path)
    with pytest.raises(ValueError, match="ISO 8601"):
        await source.changes("not-a-date")
