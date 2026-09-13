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
