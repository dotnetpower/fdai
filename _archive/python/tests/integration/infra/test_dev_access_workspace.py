from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_WORKSPACE = Path(__file__).resolve().parents[3] / "tools/dev-access/scripts/workspace.sh"


@pytest.mark.parametrize(
    ("pin", "override", "expected"),
    [
        (None, None, "inherited"),
        ("dev-secondary\n", None, "dev-secondary"),
        ("default\n", None, "default"),
        ("dev-secondary\n", "default", "default"),
        (None, "dev-secondary", "dev-secondary"),
        ("../default\n", None, None),
        ("", None, None),
        ("dev-secondary\n", "", None),
        ("dev-secondary\n", "bad workspace", None),
    ],
)
def test_workspace_pin_is_explicit_and_does_not_fall_back(
    tmp_path: Path, pin: str | None, override: str | None, expected: str | None
) -> None:
    if pin is not None:
        profiles = tmp_path / ".profiles"
        profiles.mkdir()
        (profiles / "active-workspace").write_text(pin, encoding="utf-8")
    environment = {**os.environ, "ROOT_DIR": str(tmp_path), "TF_WORKSPACE": "inherited"}
    environment.pop("FDAI_DEV_ACCESS_WORKSPACE", None)
    if override is not None:
        environment["FDAI_DEV_ACCESS_WORKSPACE"] = override
    bash = shutil.which("bash")
    assert bash is not None
    completed = subprocess.run(  # noqa: S603 - controlled helper and arguments.
        [
            bash,
            "-c",
            'set -euo pipefail; source "$1"; printf "%s\\n" "$TF_WORKSPACE"',
            "_",
            str(_WORKSPACE),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    if expected is None:
        assert completed.returncode == 21
        assert "invalid dev-access workspace" in completed.stderr
        assert completed.stdout == ""
    else:
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout == f"{expected}\n"
