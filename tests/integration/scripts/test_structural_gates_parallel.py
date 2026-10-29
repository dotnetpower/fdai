"""Contracts for the concurrent pre-push structural gate runner."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "scripts/automation/run-pre-push-structural-gates.sh"
GATES = re.findall(r"^  (scripts/quality/[\w/.-]+)$", RUNNER.read_text(encoding="utf-8"), re.M)


def _repository(tmp_path: Path, *, failing: str | None = None, delay: float = 0.0) -> Path:
    repository = tmp_path / "repo"
    for gate in GATES:
        path = repository / gate
        path.parent.mkdir(parents=True, exist_ok=True)
        body = f"sleep {delay}\n"
        if failing and gate.endswith(failing):
            body += 'echo "boom from the gate"\nexit 3\n'
        path.write_text(body, encoding="utf-8")
    runner = repository / "scripts/automation/run-pre-push-structural-gates.sh"
    runner.parent.mkdir(parents=True, exist_ok=True)
    runner.write_text(RUNNER.read_text(encoding="utf-8"), encoding="utf-8")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    # The project-version Python gates run through `uv run --extra dev python <gate>`; execute the
    # stub gate as a shell script instead.
    uv = binaries / "uv"
    uv.write_text('#!/bin/sh\nfor last; do :; done\nexec /usr/bin/bash "$last"\n', encoding="utf-8")
    uv.chmod(0o755)
    return repository


def _run(repository: Path, tmp_path: Path, jobs: int) -> subprocess.CompletedProcess[str]:
    environment = {
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
        "CI": "true",
        "FDAI_STRUCTURAL_JOBS": str(jobs),
        "HOME": str(tmp_path),
    }
    return subprocess.run(  # noqa: S603
        ["/usr/bin/bash", "scripts/automation/run-pre-push-structural-gates.sh"],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_runner_lists_every_structural_gate() -> None:
    assert len(GATES) == 11
    assert all((ROOT / gate).is_file() for gate in GATES)


def test_gates_run_concurrently_and_report_in_a_stable_order(tmp_path: Path) -> None:
    repository = _repository(tmp_path, delay=0.5)
    started = time.monotonic()
    result = _run(repository, tmp_path, jobs=len(GATES))
    elapsed = time.monotonic() - started
    assert result.returncode == 0, result.stdout + result.stderr
    assert elapsed < 0.5 * len(GATES) * 0.6  # serial execution would need 5.5 s
    summary = [line for line in result.stdout.splitlines() if "status=0" in line]
    assert [line.split("gate=")[1].split()[0] for line in summary] == [
        Path(gate).name.removesuffix(".sh") for gate in GATES
    ]
    assert result.stdout.rstrip().endswith("structural-gates: OK")


@pytest.mark.parametrize("failing", ["check-design-routes.py", "check-doc-links.sh"])
def test_a_failing_gate_blocks_the_push_with_its_own_output(tmp_path: Path, failing: str) -> None:
    repository = _repository(tmp_path, failing=failing)
    result = _run(repository, tmp_path, jobs=4)
    assert result.returncode == 1
    assert f"BLOCKED - {failing.removesuffix('.sh')} failed" in result.stderr
    assert "boom from the gate" in result.stderr
    assert "structural-gates: OK" not in result.stdout


def test_a_missing_gate_is_refused_before_anything_runs(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    (repository / GATES[0]).unlink()
    result = _run(repository, tmp_path, jobs=4)
    assert result.returncode == 1
    assert "required gate is missing" in result.stderr
    assert "status=running" not in result.stdout
