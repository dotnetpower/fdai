"""Keep CLI wheel build tooling out of unrelated caller Python environments."""

from __future__ import annotations

import os
import subprocess
import sys

from tests.integration.scripts.test_standalone_kit_release_guards import ROOT, executable


def timed_function():
    source = (ROOT / "scripts/deployment/release/stage-offline-kit.sh").read_text()
    body = source.split("run_timed() {", 1)[1]
    return "run_timed() {" + body.split('\nif [[ -n "$RUNTIME_RELEASE"', 1)[0] + "\n"


def test_cli_wheel_stage_uses_its_private_environment_for_every_uv_command(tmp_path):
    tools = tmp_path / "tools"
    executable(
        tools / "uv",
        '[[ "$UV_PROJECT_ENVIRONMENT" == "$OUT/cli-build-env" ]] || exit 65\n'
        '[[ -z "${VIRTUAL_ENV:-}" ]] || exit 66\n'
        'printf "%s\\n" "$1" >>"$TEST_CALLS"\n',
    )
    source = (ROOT / "scripts/deployment/release/stage-offline-kit.sh").read_text()
    body = source.split("build_cli_wheels() {", 1)[1]
    function = "build_cli_wheels() {" + body.split('echo "-- pinned release toolchain"', 1)[0]
    caller = tmp_path / "unrelated-environment"
    caller.mkdir()
    (caller / "sentinel").write_text("retain unrelated packages")
    result = subprocess.run(  # noqa: S603 - actual stage with a non-networking uv recorder.
        ["/bin/bash", "-s"],
        input="set -euo pipefail\n" + timed_function() + function + "\nbuild_cli_wheels\n",
        env={
            **os.environ,
            "PATH": f"{tools}:/usr/bin:/bin",
            "OUT": str(tmp_path / "stage"),
            "PYTHON": sys.executable,
            "repo_root": str(ROOT),
            "UV_PROJECT_ENVIRONMENT": str(caller),
            "VIRTUAL_ENV": str(caller),
            "TEST_CALLS": str(tmp_path / "calls"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "calls").read_text().splitlines() == ["lock", "build", "export", "run"]
    assert list(caller.iterdir()) == [caller / "sentinel"]
    assert (caller / "sentinel").read_text() == "retain unrelated packages"
