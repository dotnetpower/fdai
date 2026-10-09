"""Cache publication never replaces the last good pointer on failed or mutable input."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.delivery.code_security_cache_snapshot import publish_cache_snapshot


def test_cache_generation_is_read_only_and_previous_generations_survive(tmp_path: Path) -> None:
    source = tmp_path / "cache"
    source.mkdir()
    file = source / "database.bin"
    file.write_bytes(b"generation one")
    root = tmp_path / "published"
    first = publish_cache_snapshot(source, root)
    snapshot = root / first["cache_subpath"]
    assert (snapshot / "database.bin").read_bytes() == b"generation one"
    assert (snapshot / "database.bin").stat().st_mode & 0o222 == 0
    assert publish_cache_snapshot(source, root)["cache_digest"] == first["cache_digest"]
    file.write_bytes(b"generation two")
    second = publish_cache_snapshot(source, root)
    assert second["cache_digest"] != first["cache_digest"]
    assert (snapshot / "database.bin").read_bytes() == b"generation one"
    assert json.loads((root / "current.json").read_text())["cache_digest"] == second["cache_digest"]


def test_invalid_cache_keeps_the_last_good_pointer(tmp_path: Path) -> None:
    source = tmp_path / "cache"
    source.mkdir()
    (source / "database.bin").write_bytes(b"valid")
    root = tmp_path / "published"
    publish_cache_snapshot(source, root)
    previous = (root / "current.json").read_bytes()
    (source / "link").symlink_to("database.bin")
    with pytest.raises(RuntimeError):
        publish_cache_snapshot(source, root)
    assert (root / "current.json").read_bytes() == previous


def test_cache_publication_refuses_output_inside_input_and_empty_input(tmp_path: Path) -> None:
    source = tmp_path / "empty"
    source.mkdir()
    with pytest.raises(ValueError, match="inside"):
        publish_cache_snapshot(source, source / "output")
    with pytest.raises(ValueError, match="empty"):
        publish_cache_snapshot(source, tmp_path / "output")
