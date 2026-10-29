"""Contracts for the measured pytest shard weights and their regeneration tool."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CI = ROOT / "scripts/quality/ci"


def _load(name: str, path: Path):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


UPDATE = _load("update_shard_durations", CI / "update-pytest-shard-durations.py")
SHARD = _load("pytest_shard_for_weights", CI / "pytest_shard.py")
WEIGHTS = json.loads((CI / "pytest-shard-durations.json").read_text(encoding="utf-8"))


def test_durations_report_lines_are_summed_per_file() -> None:
    totals = UPDATE.parse_durations(
        [
            "  1.50s call     tests/a/test_one.py::test_x[param]",
            "  0.25s setup    tests/a/test_one.py::test_x[param]",
            "  0.10s teardown tests/a/test_one.py::test_x[param]",
            "  2.00s call     tests/b/test_two.py::TestK::test_y",
            "=== slowest durations ===",
            "FAILED tests/a/test_one.py::test_z - boom",
        ]
    )
    assert totals == {"tests/a/test_one.py": 1.85, "tests/b/test_two.py": 2.0}


def test_weights_keep_only_existing_files_above_the_threshold(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_slow.py").write_text("", encoding="utf-8")
    (tmp_path / "tests/test_fast.py").write_text("", encoding="utf-8")
    payload = UPDATE.build_weights(
        {
            "tests/test_slow.py": 4.0,
            "tests/test_fast.py": 0.2,
            "tests/test_removed.py": 9.0,
            "../escape/test_x.py": 9.0,
            "/abs/test_y.py": 9.0,
        },
        tmp_path,
    )
    assert payload["files"] == {"tests/test_slow.py": 4.0}
    assert payload["schema_version"] == 1


def test_generated_weights_load_in_the_shard_plugin(tmp_path: Path) -> None:
    (tmp_path / "test_a.py").write_text("", encoding="utf-8")
    log = tmp_path / "pytest.log"
    log.write_text("  3.00s call     test_a.py::test_x\n", encoding="utf-8")
    output = tmp_path / "weights.json"
    assert UPDATE.main([str(log), "--output", str(output), "--repository-root", str(tmp_path)]) == 0
    default, weights = SHARD._load_duration_weights(output)
    assert default == 0.001 and weights == {Path("test_a.py"): 3.0}


def test_a_log_without_durations_is_refused(tmp_path: Path) -> None:
    log = tmp_path / "pytest.log"
    log.write_text("no durations here\n", encoding="utf-8")
    assert UPDATE.main([str(log), "--output", str(tmp_path / "w.json")]) == 1


def test_committed_weights_reference_only_existing_files() -> None:
    missing = [path for path in WEIGHTS["files"] if not (ROOT / path).is_file()]
    assert missing == [], "regenerate with scripts/quality/ci/update-pytest-shard-durations.py"


@pytest.mark.parametrize("count", [4, 8])
def test_committed_weights_split_into_balanced_shards(count: int) -> None:
    weights = {Path(path): seconds for path, seconds in WEIGHTS["files"].items()}
    assignment = SHARD._assign_shards(weights, count)
    loads = [0.0] * count
    for path, shard in assignment.items():
        loads[shard] += weights[path]
    ideal = sum(loads) / count
    assert max(loads) <= max(1.2 * ideal, max(weights.values()))
    assert min(loads) >= 0.5 * ideal
