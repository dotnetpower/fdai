from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_WRAPPER = _ROOT / "scripts/operations/code-security-scan.sh"


def _run(
    tmp_path: Path, options: list[str], overrides: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    folder = tmp_path / "source"
    folder.mkdir()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "docker.jsonl"
    docker = binaries / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['FDAI_TEST_DOCKER_LOG'], 'a') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "sys.exit(1 if sys.argv[1:3] == ['image', 'inspect'] else 0)\n"
    )
    docker.chmod(0o755)
    home = tmp_path / "scanner-home"
    (home / "cache").mkdir(parents=True)
    (home / "cache" / "prepared").write_text("controlled cache fixture")
    environment = {
        **os.environ,
        "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
        "FDAI_CODE_SECURITY_HOME": str(home),
        "FDAI_TEST_DOCKER_LOG": str(log),
    }
    for name in (
        "FDAI_CODE_SECURITY_IMAGE",
        "FDAI_CODE_SECURITY_PROVER_IMAGE",
        "FDAI_CODE_SECURITY_JS_PROVER_IMAGE",
    ):
        environment.pop(name, None)
    environment.update(overrides or {})
    result = subprocess.run(  # noqa: S603 - controlled repository wrapper and fixture arguments
        ["/bin/bash", str(_WRAPPER), str(folder), *options],
        env=environment,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, calls


@pytest.mark.parametrize(
    ("options", "target", "image"),
    [
        ([], "runtime", "fdai-code-security-scanner:local"),
        (["--prove"], "prover", "fdai-code-security-scanner:prover"),
        (["--prove-profile", "all"], "prover", "fdai-code-security-scanner:prover"),
        (
            ["--prove-profile", "javascript"],
            "prover-javascript",
            "fdai-code-security-scanner:prover-javascript",
        ),
    ],
)
def test_profile_selection_preserves_defaults_and_enables_only_explicit_proofs(
    tmp_path: Path, options: list[str], target: str, image: str
) -> None:
    result, calls = _run(tmp_path, options)
    assert result.returncode == 0, result.stderr
    build = next(call for call in calls if call[0] == "build")
    run = next(call for call in calls if call[0] == "run")
    assert build[build.index("--target") + 1] == target
    assert build[build.index("-t") + 1] == image
    assert image in run and ("--prove" in run) == bool(options)
    assert run[run.index("--network") + 1] == "none"
    if target == "prover-javascript":
        assert "other languages remain unproven" in result.stderr


def test_javascript_profile_uses_only_its_own_image_override(tmp_path: Path) -> None:
    result, calls = _run(
        tmp_path,
        ["--prove-profile", "javascript"],
        {
            "FDAI_CODE_SECURITY_PROVER_IMAGE": "controlled-full-image",
            "FDAI_CODE_SECURITY_JS_PROVER_IMAGE": "controlled-js-image",
        },
    )
    assert result.returncode == 0, result.stderr
    build = next(call for call in calls if call[0] == "build")
    assert build[build.index("-t") + 1] == "controlled-js-image"
    assert "controlled-full-image" not in build


def test_unknown_profile_fails_before_docker_or_scan_effects(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, ["--prove-profile", "native"])
    assert result.returncode == 2
    assert "--prove-profile must be all or javascript" in result.stderr
    assert calls == []
