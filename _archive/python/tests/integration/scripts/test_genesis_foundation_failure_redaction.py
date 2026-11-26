"""Direct Foundation errors never expose private provider argv or filesystem paths."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

import genesis_foundation_apply as apply  # noqa: E402
from tests.integration.scripts.test_genesis_foundation_apply import _args  # noqa: E402


@pytest.mark.parametrize("helper", [apply._capture, apply._required])
@pytest.mark.parametrize("kind", ["timeout", "filesystem"])
def test_command_helpers_redact_exception_values(monkeypatch, helper, kind):
    def failed(*_args, **_kwargs):
        if kind == "timeout":
            raise subprocess.TimeoutExpired(["az", "private-argument-marker"], 1)
        raise OSError("private-path-marker")

    monkeypatch.setattr(apply, "run_with_heartbeat", failed)
    with pytest.raises(ValueError, match="fixed failure") as caught:
        helper(["az", "show"], cwd=ROOT, timeout=1, reason="fixed failure")
    assert "private-" not in str(caught.value)


@pytest.mark.parametrize("kind", ["timeout", "filesystem"])
def test_direct_entrypoint_does_not_format_raw_external_exceptions(
    tmp_path, monkeypatch, capsys, kind
):
    def failed(_args):
        if kind == "timeout":
            raise subprocess.TimeoutExpired(["az", "private-argument-marker"], 1)
        raise OSError("private-path-marker")

    monkeypatch.setattr(apply, "_execute", failed)
    assert apply.main(_args(tmp_path, "--approve")) == 3
    assert "private-" not in capsys.readouterr().err


@pytest.mark.parametrize("failed_execution", [False, True])
def test_input_cleanup_failure_is_redacted_before_any_success(
    tmp_path, monkeypatch, capsys, failed_execution
):
    def execute(_args):
        if failed_execution:
            raise ValueError("original fixed failure")
        return {"state": "verified"}

    def unlink(*_args, **_kwargs):
        raise NotADirectoryError("private-cleanup-marker")

    monkeypatch.setattr(apply, "_execute", execute)
    monkeypatch.setattr(Path, "unlink", unlink)
    assert apply.main(_args(tmp_path, "--approve")) == 3
    output = capsys.readouterr()
    assert "private-" not in output.err
    assert "cleanup" in output.err
    assert ("original fixed failure" in output.err) is failed_execution
    assert not output.out
