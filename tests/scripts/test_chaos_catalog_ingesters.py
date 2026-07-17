"""Regression tests for the curated chaos-catalog ingesters."""

from __future__ import annotations

import pathlib
import runpy
import shutil

import pytest

from fdai.core.chaos.scenario_catalog import load_all

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "rule-catalog" / "chaos-scenarios" / "schema" / "chaos-scenario.schema.json"


@pytest.mark.parametrize(
    ("script_name", "source", "expected_count"),
    [
        ("ingest-azure-chaos-studio-catalog.py", "azure-chaos-studio", 15),
        ("ingest-aws-fis-catalog.py", "aws-fis", 17),
        ("ingest-chaos-mesh-catalog.py", "chaos-mesh", 14),
        ("ingest-litmus-catalog.py", "litmus", 16),
    ],
)
def test_ingester_output_is_valid_and_deterministic(
    tmp_path: pathlib.Path,
    script_name: str,
    source: str,
    expected_count: int,
) -> None:
    root = tmp_path / "chaos-scenarios"
    schema_dir = root / "schema"
    schema_dir.mkdir(parents=True)
    shutil.copyfile(_SCHEMA, schema_dir / _SCHEMA.name)
    out_dir = root / "collected" / source

    namespace = runpy.run_path(str(_REPO_ROOT / "scripts" / script_name))
    main = namespace["main"]
    assert callable(main)
    main.__globals__["_OUT_DIR"] = out_dir

    assert main() == 0
    first = {path.name: path.read_bytes() for path in sorted(out_dir.glob("*.yaml"))}
    assert len(first) == expected_count

    entries = load_all(root=root)
    assert len(entries) == expected_count
    assert {entry.spec["provenance"]["source"] for entry in entries} == {source}

    assert main() == 0
    second = {path.name: path.read_bytes() for path in sorted(out_dir.glob("*.yaml"))}
    assert second == first
