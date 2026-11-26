"""Catch stale semantic inventory locally without rewriting evaluation evidence."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import NoReturn

import pytest
from scripts.automation import build_semantic_intent_coverage as inventory_builder

_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def inventory_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, dict[str, object]]:
    payload: dict[str, object] = {"source_digests": {"source": "current"}, "coverage_metrics": {}}

    def forbid_write(path: Path, content: str) -> NoReturn:
        raise AssertionError("read-only inventory check attempted to write")

    monkeypatch.setattr(inventory_builder, "build_inventory", lambda root: payload)
    monkeypatch.setattr(inventory_builder, "_write_text", forbid_write)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_semantic_intent_coverage.py",
            "--root",
            str(tmp_path),
            "--output",
            "out.json",
            "--check",
        ],
    )
    return tmp_path / "out.json", payload


def test_missing_inventory_fails_without_creating_output(
    inventory_check: tuple[Path, dict[str, object]], capsys: pytest.CaptureFixture[str]
) -> None:
    output, _ = inventory_check
    assert inventory_builder.main() == 1
    assert not output.exists()
    assert "stale generated artifact" in capsys.readouterr().err


@pytest.mark.parametrize("content", ["{}", "not JSON", '{"source_digests":{"source":"old"}}'])
def test_stale_inventory_fails_without_rewriting(
    inventory_check: tuple[Path, dict[str, object]], content: str
) -> None:
    output, _ = inventory_check
    output.write_text(content, encoding="utf-8")
    assert inventory_builder.main() == 1
    assert output.read_text(encoding="utf-8") == content


def test_current_inventory_passes_without_rewriting(
    inventory_check: tuple[Path, dict[str, object]], capsys: pytest.CaptureFixture[str]
) -> None:
    output, payload = inventory_check
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output.write_text(content, encoding="utf-8")
    before = output.stat().st_mtime_ns
    assert inventory_builder.main() == 0
    assert output.read_text(encoding="utf-8") == content
    assert output.stat().st_mtime_ns == before
    assert "matches authoritative sources" in capsys.readouterr().out


def test_diff_gate_covers_every_recorded_source_and_the_original_missed_path() -> None:
    verify = (_ROOT / "scripts/verify.sh").read_text(encoding="utf-8")
    match = re.search(r"""run_gate_scoped "semantic-intent-coverage" '([^']+)'""", verify)
    assert match is not None
    scope = re.compile(match.group(1))
    sources = inventory_builder.build_inventory(_ROOT)["source_digests"]
    for path in (
        *sources,
        "services/core-control-plane/src/fdai/core/ontology_platform/inventory_projection_bounds.py",
        "scripts/automation/build_semantic_intent_coverage.py",
        "scripts/verify.sh",
        "tests/integration/scripts/test_semantic_inventory_check.py",
    ):
        assert scope.search(path), path
    assert scope.search("site/src/unrelated.astro") is None
