from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def test_retired_genesis_wrapper_fails_before_any_azure_change() -> None:
    root = Path(__file__).resolve().parents[3]
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(  # noqa: S603 - fixed repository wrapper under test.
        [bash, "scripts/deployment/azure/genesis-up.sh"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "canonical deployment CLI" in result.stderr
    assert "No Azure change was attempted" in result.stderr
    assert "terraform " not in result.stdout
