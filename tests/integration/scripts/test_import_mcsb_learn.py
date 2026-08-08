"""Tests for the bounded MCSB v2 Microsoft Learn importer."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "catalog" / "import_mcsb_learn.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("import_mcsb_learn", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _page(*headings: tuple[str, str], commit: str = "a" * 40) -> bytes:
    controls = "".join(
        f'<h2 id="{control_id.lower()}">{control_id}: {title}</h2>'
        for control_id, title in headings
    )
    return (
        f'<html><head><meta name="git_commit_id" content="{commit}" /></head>'
        f"<body>{controls}</body></html>"
    ).encode()


def test_extracts_top_level_controls_and_source_revision() -> None:
    module = _module()

    snapshot = module.parse_domain_page(
        "AI",
        "https://learn.microsoft.com/security/benchmark/azure/mcsb-v2-ai",
        _page(("AI-1", "Use approved models"), ("AI-2", "Filter content")),
    )

    assert snapshot.resolved_ref == "a" * 40
    assert snapshot.controls == (
        {"id": "AI-1", "domain": "AI", "title": "Use approved models"},
        {"id": "AI-2", "domain": "AI", "title": "Filter content"},
    )
    assert snapshot.content_hash.startswith("sha256:")


def test_rejects_missing_commit_and_duplicate_controls() -> None:
    module = _module()
    with pytest.raises(ValueError, match="no immutable git commit"):
        module.parse_domain_page(
            "AI",
            "https://learn.microsoft.com/",
            b'<h2 id="ai-1">AI-1: A</h2>',
        )
    with pytest.raises(ValueError, match="duplicate control ids"):
        module.parse_domain_page(
            "AI",
            "https://learn.microsoft.com/",
            _page(("AI-1", "A"), ("AI-1", "B")),
        )
