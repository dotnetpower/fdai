from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "governance" / "check-stewardship.sh"


def _run(*, path: str) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash is not None
    return subprocess.run(  # noqa: S603 - resolved bash executes one fixed repository script
        [bash, str(_SCRIPT)],
        cwd=_ROOT,
        env={**os.environ, "PATH": path},
        check=False,
        capture_output=True,
        text=True,
    )


def test_stewardship_gate_validates_with_repository_python() -> None:
    python_directory = str(Path(sys.executable).parent)

    result = _run(path=f"{python_directory}:{os.environ['PATH']}")

    assert result.returncode == 0, result.stderr
    assert "check-stewardship: OK (15 agents, " in result.stdout
    assert "maintainer(s))" in result.stdout


def test_stewardship_gate_fails_when_yaml_parser_is_unavailable(tmp_path: Path) -> None:
    python = tmp_path / "python3"
    python.write_text(
        f'#!/usr/bin/env bash\nexec {sys.executable!s} -S "$@"\n',
        encoding="utf-8",
    )
    python.chmod(0o755)

    result = _run(path=f"{tmp_path}:{os.environ['PATH']}")

    assert result.returncode == 1
    assert "PyYAML is required for structural validation" in result.stderr
    assert "skipping" not in result.stdout.lower()
    assert "skipping" not in result.stderr.lower()
