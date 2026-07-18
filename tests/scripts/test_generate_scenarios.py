"""Regression tests for the deterministic chaos-scenario seed generator."""

from __future__ import annotations

import pathlib
import runpy
import shutil

from fdai.core.chaos.scenario_catalog import load_all

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "catalog" / "generate-scenarios.py"
_SCHEMA = _REPO_ROOT / "rule-catalog" / "chaos-scenarios" / "schema" / "chaos-scenario.schema.json"


def test_seed_generator_is_valid_and_deterministic(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "chaos-scenarios"
    schema_dir = root / "schema"
    schema_dir.mkdir(parents=True)
    shutil.copyfile(_SCHEMA, schema_dir / _SCHEMA.name)

    namespace = runpy.run_path(str(_SCRIPT))
    general_specs = namespace["_general_specs"]
    gpu_specs = namespace["_gpu_specs"]
    write = namespace["_write"]
    assert callable(general_specs)
    assert callable(gpu_specs)
    assert callable(write)

    first_general = general_specs()
    first_gpu = gpu_specs()
    assert len(first_general) == 48
    assert len(first_gpu) == 22
    assert len({spec.id for spec in (*first_general, *first_gpu)}) == 70

    for spec in first_general:
        write(spec, root / "collected" / "synthesized")
    for spec in first_gpu:
        write(spec, root / "collected" / "gpu")

    entries = load_all(root=root)
    assert len(entries) == 70
    assert all(entry.shadow_status == "pending" for entry in entries)
    assert all(entry.enforce_status is None for entry in entries)

    second_bodies = [spec.to_yaml_body() for spec in (*general_specs(), *gpu_specs())]
    first_bodies = [spec.to_yaml_body() for spec in (*first_general, *first_gpu)]
    assert second_bodies == first_bodies
