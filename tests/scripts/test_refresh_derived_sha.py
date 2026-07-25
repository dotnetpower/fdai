"""Derived-document source SHA refresh tests."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "quality"
    / "localization"
    / "refresh-derived-sha.py"
)


@pytest.fixture(scope="module")
def refresh_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_derived_sha", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    payload = path.read_bytes()
    return hashlib.sha1(  # noqa: S324 - Git blob compatibility, not security
        b"blob " + str(len(payload)).encode() + b"\x00" + payload,
        usedforsecurity=False,
    ).hexdigest()


def test_refreshes_inline_derived_source_sha(
    tmp_path: Path,
    refresh_module: ModuleType,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("source\n", encoding="utf-8")
    doc = tmp_path / "guide.md"
    doc.write_text(
        "---\nderives_from: [{ source: source.md, sha: stale }]\n---\n# Guide\n",
        encoding="utf-8",
    )

    changed, _ = refresh_module.process(tmp_path, doc)

    assert changed is True
    assert f"sha: {_sha(source)}" in doc.read_text(encoding="utf-8")


def test_refreshes_multiline_derived_source_sha(
    tmp_path: Path,
    refresh_module: ModuleType,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("source\n", encoding="utf-8")
    doc = tmp_path / "guide.md"
    doc.write_text(
        "---\nderives_from:\n  - source: source.md\n    sha: stale\n---\n# Guide\n",
        encoding="utf-8",
    )

    changed, _ = refresh_module.process(tmp_path, doc)

    assert changed is True
    assert f"sha: {_sha(source)}" in doc.read_text(encoding="utf-8")
