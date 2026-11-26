"""Regression tests for the curated chaos-catalog ingesters."""

from __future__ import annotations

import pathlib
import runpy
import shutil

import pytest
from fdai.core.chaos.scenario_catalog import load_all

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_SCHEMA = _REPO_ROOT / "rule-catalog" / "chaos-scenarios" / "schema" / "chaos-scenario.schema.json"


@pytest.mark.parametrize(
    ("script_name", "source", "expected_count"),
    [
        ("ingest-azure-chaos-studio-catalog.py", "azure-chaos-studio", 15),
        ("ingest-aws-fis-catalog.py", "aws-fis", 42),
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
    out_dir.mkdir(parents=True, exist_ok=True)
    stale_file = out_dir / "obsolete-stale-entry.yaml"
    stale_file.write_text("id: chaos.stale.entry\n", encoding="utf-8")

    namespace = runpy.run_path(str(_REPO_ROOT / "scripts" / "catalog" / script_name))
    main = namespace["main"]
    assert callable(main)
    main.__globals__["_OUT_DIR"] = out_dir

    assert main() == 0
    assert not stale_file.exists()
    first = {path.name: path.read_bytes() for path in sorted(out_dir.glob("*.yaml"))}
    assert len(first) == expected_count

    entries = load_all(root=root)
    assert len(entries) == expected_count
    assert {entry.spec["provenance"]["source"] for entry in entries} == {source}

    assert main() == 0
    second = {path.name: path.read_bytes() for path in sorted(out_dir.glob("*.yaml"))}
    assert second == first


@pytest.mark.parametrize(
    "script_name",
    [
        "ingest-azure-chaos-studio-catalog.py",
        "ingest-aws-fis-catalog.py",
        "ingest-chaos-mesh-catalog.py",
        "ingest-litmus-catalog.py",
    ],
)
def test_curated_ingesters_reject_invalid_slug_and_rca_only_signals(
    script_name: str,
) -> None:
    from dataclasses import replace

    namespace = runpy.run_path(str(_REPO_ROOT / "scripts" / "catalog" / script_name))
    validate = namespace["_validate_entry"]
    sample = namespace["_ENTRIES"][0]

    with pytest.raises(ValueError, match="invalid_slug"):
        validate(replace(sample, slug="Bad_Slug"))
    with pytest.raises(ValueError, match="unknown_expected_signal"):
        validate(replace(sample, expected_signal="no_such_signal"))
    with pytest.raises(ValueError, match="rca_only_signal_not_scenario_eligible"):
        validate(replace(sample, expected_signal="member_hotspot"))
