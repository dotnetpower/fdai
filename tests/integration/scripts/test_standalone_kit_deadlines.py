"""Exercise complete-release supervision without Docker, network, or real signing."""

from __future__ import annotations

import subprocess

import pytest
from tests.integration.scripts.test_standalone_kit_release_guards import (
    BUILDER,
    bounded_environment,
    bounded_prelude,
)


def run_stage(script):
    return subprocess.run(  # noqa: S603 - fixed release supervisor and synthetic child.
        ["/bin/bash", "-s"],
        input=bounded_prelude() + script,
        env=bounded_environment(),
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_silent_build_stops_before_signing_or_success():
    result = run_stage(
        'bounded_stage silent-build 5 1 "$python" -c "import signal; signal.pause()"\n'
        'echo "unexpected-signing"\necho "standalone-kit: OK"\n'
    )
    assert result.returncode == 124
    assert "no-progress-1s" in result.stderr
    assert "unexpected-signing" not in result.stdout
    assert "standalone-kit: OK" not in result.stdout


def test_release_budget_caps_the_next_stage():
    result = run_stage(
        "release_deadline=$((SECONDS + 1))\n"
        'bounded_stage total-budget 60 60 "$python" -c "import signal; signal.pause()"\n'
    )
    assert result.returncode == 124
    assert "exceeded-total-1s" in result.stderr


def test_expired_release_does_not_launch_another_child():
    result = run_stage(
        "release_deadline=$SECONDS\n"
        'bounded_stage expired 60 60 "$python" -c "print(\'unexpected-child\')"\n'
    )
    assert result.returncode == 124
    assert "total build deadline exceeded" in result.stderr
    assert "unexpected-child" not in result.stdout


def test_supervisor_preserves_heredoc_environment_and_exit_status():
    result = run_stage(
        "SYNTHETIC_STAGE_VALUE=ready bounded_stage heredoc 5 5 \"$python\" - <<'PY'\n"
        'import os\nprint(os.environ["SYNTHETIC_STAGE_VALUE"])\nraise SystemExit(17)\nPY\n'
        'echo "unexpected-followup"\n'
    )
    assert result.returncode == 17
    assert result.stdout == "ready\n"


@pytest.mark.parametrize(
    "command",
    ["docker buildx build", 'npm --prefix "$repo_root/console"', "tar --sort=name"],
)
def test_every_expensive_direct_build_uses_supervision(command):
    lines = [line for line in BUILDER.read_text().splitlines() if command in line]
    assert lines
    assert all(line.lstrip().startswith("bounded_stage ") for line in lines)
