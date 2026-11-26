from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def test_genesis_wrapper_requires_an_explicit_target_before_azure(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    bash = shutil.which("bash")
    assert bash is not None
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "azure-called"
    az = fake_bin / "az"
    az.write_text(f"#!/usr/bin/env bash\ntouch {marker!s}\n", encoding="ascii")
    az.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "AZURE_SUBSCRIPTION_ID": "",
        "AZURE_TENANT_ID": "",
    }
    result = subprocess.run(  # noqa: S603 - fixed repository wrapper under test.
        [bash, "scripts/deployment/azure/genesis-up.sh"],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 64
    assert "genesis-up: invalid_azure_target" in result.stderr
    assert result.stdout == ""
    assert not marker.exists()
