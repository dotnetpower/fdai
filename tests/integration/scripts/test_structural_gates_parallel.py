"""Contracts for the concurrent pre-push structural gate runner."""

from __future__ import annotations

import re
import signal
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


def _environment(tmp_path: Path, jobs: int | str) -> dict[str, str]:
    return {
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
        "CI": "true",
        "FDAI_STRUCTURAL_JOBS": str(jobs),
        "HOME": str(tmp_path),
    }


def _run(
    repository: Path, tmp_path: Path, jobs: int | str, **overrides: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["/usr/bin/bash", "scripts/automation/run-pre-push-structural-gates.sh"],
        cwd=repository,
        env=_environment(tmp_path, jobs) | overrides,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
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
    assert "status=3" in result.stderr
    assert "boom from the gate" in result.stderr
    assert "structural-gates: OK" not in result.stdout


def test_a_missing_gate_is_refused_before_anything_runs(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    (repository / GATES[0]).unlink()
    result = _run(repository, tmp_path, jobs=4)
    assert result.returncode == 1
    assert "required gate is missing" in result.stderr
    assert "status=running" not in result.stdout


@pytest.mark.parametrize("jobs", ["", "0", "-1", "1.5", "abc", "01", "65", "1+1", "9" * 30])
def test_invalid_parallelism_is_rejected_before_launch(tmp_path: Path, jobs: str) -> None:
    repository = _repository(tmp_path)
    result = _run(repository, tmp_path, jobs=jobs)
    assert result.returncode == 125
    assert "FDAI_STRUCTURAL_JOBS must be an integer from 1 to 64" in result.stderr
    assert "status=running" not in result.stdout
    assert not list(repository.glob(".fdai-structural-gates.*"))


@pytest.mark.parametrize("deadline", ["", "0", "-1", "1.5", "01", "3601", "9" * 30])
def test_invalid_total_deadline_is_rejected(tmp_path: Path, deadline: str) -> None:
    repository = _repository(tmp_path)
    result = _run(repository, tmp_path, jobs=1, FDAI_STRUCTURAL_TIMEOUT_SECONDS=deadline)
    assert result.returncode == 125
    assert "FDAI_STRUCTURAL_TIMEOUT_SECONDS must be an integer from 1 to 3600" in result.stderr
    assert "status=running" not in result.stdout


def _wait_for_file(path: Path) -> None:
    deadline = time.monotonic() + 5
    while not path.exists() or not path.read_text(encoding="utf-8").strip():
        assert time.monotonic() < deadline, f"worker did not start: {path}"
        time.sleep(0.01)


def _hanging_gate(repository: Path) -> list[Path]:
    (repository / GATES[0]).write_text(
        'echo "$$" >gate.pid\n'
        'bash -c \'echo "$$" >descendant.pid; trap "" TERM; '
        "while :; do sleep 0.1; done' &\n"
        "wait\n",
        encoding="utf-8",
    )
    return [repository / "gate.pid", repository / "descendant.pid"]


def _assert_workers_stopped(pid_files: list[Path]) -> None:
    for path in pid_files:
        pid = int(path.read_text(encoding="utf-8"))
        stat = Path(f"/proc/{pid}/stat")
        # A terminated orphan can briefly remain as a zombie until init reaps it.
        assert not stat.exists() or stat.read_text(encoding="utf-8").split()[2] == "Z"


@pytest.mark.parametrize("jobs", [1, len(GATES)])
def test_total_deadline_cancels_running_and_queued_gates(tmp_path: Path, jobs: int) -> None:
    repository = _repository(tmp_path)
    pid_files = _hanging_gate(repository)
    result = _run(repository, tmp_path, jobs=jobs, FDAI_STRUCTURAL_TIMEOUT_SECONDS="2")
    assert result.returncode == 124, result.stdout + result.stderr
    assert "total deadline exceeded (2s)" in result.stderr
    assert "structural-gates: OK" not in result.stdout
    if jobs == 1:
        assert result.stdout.count("status=running") == 1
    _assert_workers_stopped(pid_files)
    assert not list(repository.glob(".fdai-structural-gates.*"))


@pytest.mark.parametrize("cancel_signal", [signal.SIGTERM, signal.SIGINT])
def test_cancellation_cleans_only_owned_workers(
    tmp_path: Path, cancel_signal: signal.Signals
) -> None:
    repository = _repository(tmp_path)
    pid_files = _hanging_gate(repository)
    unrelated = subprocess.Popen(["/usr/bin/sleep", "30"])  # noqa: S603
    runner = subprocess.Popen(  # noqa: S603
        ["/usr/bin/bash", "scripts/automation/run-pre-push-structural-gates.sh"],
        cwd=repository,
        env=_environment(tmp_path, 1),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for path in pid_files:
            _wait_for_file(path)
        runner.send_signal(cancel_signal)
        stdout, stderr = runner.communicate(timeout=5)
        assert runner.returncode == 128 + cancel_signal
        assert "cancelled by" in stderr
        assert "structural-gates: OK" not in stdout
        _assert_workers_stopped(pid_files)
        assert unrelated.poll() is None
        assert not list(repository.glob(".fdai-structural-gates.*"))
    finally:
        if runner.poll() is None:
            runner.terminate()
            runner.communicate(timeout=5)
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_a_worker_that_dies_without_a_result_blocks_the_push(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    (repository / GATES[0]).write_text(
        'worker="$(ps -o ppid= -p "$PPID")"\nkill -KILL "$worker"\nexec sleep 30\n',
        encoding="utf-8",
    )
    result = _run(repository, tmp_path, jobs=1)
    assert result.returncode == 1
    assert "failed: missing or invalid result" in result.stderr
    assert "structural-gates: OK" not in result.stdout
    assert not list(repository.glob(".fdai-structural-gates.*"))


def test_gate_failures_are_reported_in_declared_order(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    for gate, code in [(GATES[0], 4), (GATES[-1], 124)]:
        (repository / gate).write_text(f"exit {code}\n", encoding="utf-8")
    result = _run(repository, tmp_path, jobs=64, FDAI_STRUCTURAL_TIMEOUT_SECONDS="3600")
    assert result.returncode == 1
    failures = [line for line in result.stderr.splitlines() if "failed:" in line]
    assert Path(GATES[0]).stem in failures[0] and "status=4" in failures[0]
    assert Path(GATES[-1]).stem in failures[1] and "status=124" in failures[1]


def test_non_ci_entrypoint_still_uses_the_validation_cache(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    python = tmp_path / "bin/python3"
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n', encoding="utf-8")
    python.chmod(0o755)
    result = _run(repository, tmp_path, jobs=1, CI="false")
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "scripts/automation/local_validation_cache.py",
        "structural",
    ]
    assert "status=running" not in result.stdout
