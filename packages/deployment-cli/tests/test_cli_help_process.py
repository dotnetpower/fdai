"""Fresh-process help must work without Azure tools, credentials, stdin, or writable state."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "src"
_GUARDED_ENTRY = """
import os
import sys

def guard(event, args):
    if event in {"subprocess.Popen", "os.system", "os.mkdir", "os.remove", "os.rename", "builtins.input"}:
        raise RuntimeError("unexpected help side effect: " + event)
    if event.startswith("socket."):
        raise RuntimeError("unexpected help network access")
    if event == "open":
        path, mode, flags = args
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            raise RuntimeError("unexpected help file write")
        if isinstance(path, str) and path.startswith(os.environ["HOME"]):
            raise RuntimeError("unexpected help private-state read")

sys.addaudithook(guard)
from fdai_deployment_cli.cli import main
raise SystemExit(main())
"""


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["-h"],
        ["--help"],
        ["--version"],
        ["version"],
        ["version", "--output", "json"],
        ["offline"],
        ["provision"],
        ["bundle"],
        ["license"],
        ["onboard"],
        ["doctor", "--help"],
        ["offline", "prepare", "--help"],
        ["offline", "configure-console", "--help"],
        ["offline", "install-support", "--help"],
        ["provision", "azure", "--help"],
        ["provision", "init", "--help"],
        ["provision", "inspect", "--help"],
        ["provision", "plan", "--help"],
        ["provision", "bootstrap-reconcile", "--help"],
        ["provision", "verify-state-handoff", "--help"],
        ["provision", "verify-foundation-plan", "--help"],
        ["bundle", "verify", "--help"],
        ["license", "inspect", "--help"],
        ["onboard", "guided", "--help"],
        ["onboard", "status", "--help"],
    ],
)
def test_fresh_help_has_no_operational_side_effects(arguments, tmp_path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    completed = subprocess.run(
        [sys.executable, "-c", _GUARDED_ENTRY, *arguments],
        cwd=tmp_path,
        env={
            "HOME": str(home),
            "PATH": str(tmp_path / "no-tools"),
            "PYTHONPATH": str(SOURCE),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
            "TERM": "dumb",
            "COLUMNS": "80",
            "FORCE_COLOR": "1",
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert completed.stdout
    assert "\x1b" not in completed.stdout
    assert not list(home.iterdir())
    assert list(tmp_path.iterdir()) == [home]
