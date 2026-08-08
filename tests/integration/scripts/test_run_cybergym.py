"""CyberGym CLI tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.benchmarking import run_cybergym
from scripts.benchmarking.cybergym_runtime import CyberGymPaths


class _Runtime:
    def __init__(self, *, ready: bool) -> None:
        self._ready = ready

    def readiness(self, task: str, *, mode: str) -> dict[str, bool]:
        assert task == "example/task-1"
        assert mode == "e2e"
        return {"docker": self._ready, "task": True}


@pytest.mark.parametrize(("ready", "expected"), ((True, 0), (False, 2)))
def test_check_emits_machine_readable_readiness(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    ready: bool,
    expected: int,
) -> None:
    paths = CyberGymPaths(tmp_path, tmp_path, tmp_path, tmp_path)
    monkeypatch.setattr(
        run_cybergym,
        "_composition",
        lambda args: (_Runtime(ready=ready), paths),
    )

    exit_code = run_cybergym.main(("check", "example/task-1"))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == expected
    assert payload["ready"] is ready
    assert payload["shadow_only"] is True


def test_process_boundary_redacts_exception_detail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(args: object) -> None:
        raise RuntimeError("sensitive provider detail")

    monkeypatch.setattr(run_cybergym, "_composition", fail)

    exit_code = run_cybergym.main(("check", "example/task-1"))

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "sensitive provider detail" not in captured.err
    assert json.loads(captured.err)["error_type"] == "RuntimeError"
