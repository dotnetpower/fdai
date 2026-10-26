"""Exercise shard selection in real pytest processes, including xdist workers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]
_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def shard_project(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    monkeypatch.setenv("PYTHONPATH", str(_ROOT))
    monkeypatch.setenv("FDAI_PYTEST_SHARD_COUNT", "2")
    monkeypatch.setenv("FDAI_PYTEST_MODE", "regression")
    monkeypatch.delenv("FDAI_PYTEST_DURATION_REPORT", raising=False)
    pytester.makeini("[pytest]\ntestpaths = tests\n")
    pytester.makeconftest('pytest_plugins = ["scripts.quality.ci.pytest_shard"]')
    tests = pytester.path / "tests"
    tests.mkdir()
    for name in ("a", "b", "c", "d"):
        (tests / f"test_{name}.py").write_text(
            "from pathlib import Path\n"
            "import pytest\n"
            f"Path(__file__).with_suffix('.imported').touch()\n"
            "@pytest.mark.parametrize('value', range(3))\n"
            f"def test_{name}(value):\n"
            "    assert value >= 0\n",
            encoding="utf-8",
        )
    return pytester


@pytest.mark.parametrize("parallel", [False, True])
def test_shards_import_only_owned_files_and_preserve_every_case(
    shard_project: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    parallel: bool,
) -> None:
    options = ["-q", "--no-cov"]
    if parallel:
        options.extend(["-n", "2", "--dist=worksteal"])
    reported: list[set[str]] = []
    for index, expected_names in [(1, {"a", "c"}), (2, {"b", "d"})]:
        monkeypatch.setenv("FDAI_PYTEST_SHARD_INDEX", str(index))
        report_path = shard_project.path / f"durations-{index}.json"
        monkeypatch.setenv("FDAI_PYTEST_DURATION_REPORT", str(report_path))
        result = shard_project.runpytest_subprocess(*options)
        result.assert_outcomes(passed=6)
        imported = {
            path.stem.removeprefix("test_")
            for path in (shard_project.path / "tests").glob("*.imported")
        }
        assert imported == expected_names
        for path in (shard_project.path / "tests").glob("*.imported"):
            path.unlink()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["shard_index"] == index
        assert report["shard_count"] == 2
        assert report["exit_status"] == 0
        assert report["mode"] == "regression"
        assert all(value > 0 for value in report["files"].values())
        reported.append(set(report["files"]))
    assert not reported[0] & reported[1]
    assert reported[0] | reported[1] == {f"tests/test_{name}.py" for name in ("a", "b", "c", "d")}


def test_explicit_node_ids_still_obey_file_ownership(
    shard_project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in (1, 2):
        monkeypatch.setenv("FDAI_PYTEST_SHARD_INDEX", str(index))
        result = shard_project.runpytest_subprocess(
            "-q", "--no-cov", "tests/test_a.py::test_a", "tests/test_b.py::test_b"
        )
        result.assert_outcomes(passed=3, deselected=3)


def test_failed_tests_leave_explicitly_failed_timing_evidence(
    shard_project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FDAI_PYTEST_SHARD_INDEX", "1")
    report_path = shard_project.path / "failed-durations.json"
    monkeypatch.setenv("FDAI_PYTEST_DURATION_REPORT", str(report_path))
    (shard_project.path / "tests/test_a.py").write_text("def test_failure():\n    assert False\n")
    result = shard_project.runpytest_subprocess("-q", "--no-cov")
    result.assert_outcomes(passed=3, failed=1)
    assert json.loads(report_path.read_text(encoding="utf-8"))["exit_status"] == 1


def test_ignored_files_and_marker_selection_preserve_the_selected_union(
    shard_project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    tests = shard_project.path / "tests"
    (tests / "test_a.py").write_text(
        "import pytest\n@pytest.mark.integration\ndef test_selected():\n    assert True\n"
    )
    (tests / "test_b.py").write_text(
        "import pytest\n@pytest.mark.integration\ndef test_also_selected():\n    assert True\n"
    )
    (tests / "test_c.py").write_text("raise AssertionError('ignored file was imported')\n")
    results: list[int] = []
    for index in (1, 2):
        monkeypatch.setenv("FDAI_PYTEST_SHARD_INDEX", str(index))
        result = shard_project.runpytest_subprocess(
            "-q",
            "--no-cov",
            "-m",
            "integration",
            "--ignore=tests/test_c.py",
            "-o",
            "markers=integration: database tests",
        )
        assert result.ret == 0
        results.append(result.parseoutcomes()["passed"])
    assert results == [1, 1]
