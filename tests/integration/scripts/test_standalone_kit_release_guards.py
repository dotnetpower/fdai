"""Exercise release shell guards without Docker, signing, downloads, or Azure effects."""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BUILDER = ROOT / "scripts/deployment/release/build-standalone-deployment-kit.sh"


def executable(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\n" + content)
    path.chmod(0o700)


@pytest.mark.parametrize("output_kind", ["directory", "symlink"])
def test_existing_release_output_cannot_be_erased(tmp_path, output_kind):
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = tmp_path / "tools"
    tools.mkdir()
    executable(
        tools / "git",
        'if [[ "$*" == *"--show-toplevel"* ]]; then printf "%s\\n" "$TEST_ROOT"; '
        'elif [[ "$*" == *"--porcelain"* ]]; then exit 0; '
        'elif [[ "$*" == *"--format=%ct"* ]]; then echo 1700000000; '
        'else printf "%040d\\n" 1; fi\n',
    )
    executable(
        repo / ".venv/bin/python",
        'if [[ "$*" == *"__version__"* ]]; then echo 0.1.0; '
        'elif [[ "$*" == *"RUNTIME_SERVICES"* ]]; then echo core-control-plane; '
        'elif [[ "$1" == *workdir-guard.py ]]; then '
        'exec "$TEST_PYTHON" "$TEST_GUARD" "${@:2}"; '
        "else cat >/dev/null; fi\n",
    )
    for tool in ("docker", "node", "npm"):
        executable(tools / tool, "exit 65\n")
    key = tmp_path / "synthetic-key"
    key.write_text("synthetic prerequisite, never used for signing")
    key.chmod(0o600)
    owned = tmp_path / "owned"
    owned.mkdir(mode=0o700)
    sentinel = owned / ".fdai-standalone-release"
    sentinel.write_text("fdai-standalone-release-v1\n")
    sentinel.chmod(0o600)
    archive = owned / "fdai-deployment-kit-0.1.0-linux-x86_64.tar.gz"
    archive.write_bytes(b"retained signed archive sentinel")
    source = owned / "release-input"
    source.mkdir()
    (source / "sentinel").write_text("retained source")
    output = tmp_path / "alias" if output_kind == "symlink" else owned
    if output_kind == "symlink":
        output.symlink_to(owned, target_is_directory=True)
    result = subprocess.run(  # noqa: S603 - fixed release script with synthetic tool boundaries.
        [
            "/bin/bash",
            str(BUILDER),
            "--out",
            str(output),
            "--release-key",
            str(key),
            "--bundle-key",
            str(key),
        ],
        cwd=repo,
        env={
            **os.environ,
            "PATH": f"{tools}:/usr/bin:/bin",
            "TEST_ROOT": str(repo),
            "TEST_PYTHON": sys.executable,
            "TEST_GUARD": str(ROOT / "scripts/deployment/release/workdir-guard.py"),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert archive.read_bytes() == b"retained signed archive sentinel"
    assert (source / "sentinel").read_text() == "retained source"
    assert "fresh output directory" in result.stderr


@pytest.mark.parametrize("checksum", ["exit 74", "exit 0", "echo invalid"])
def test_archive_digest_failure_cannot_report_success(tmp_path, checksum):
    tools = tmp_path / "tools"
    tools.mkdir()
    executable(tools / "tar", 'printf "archive" >"$TEST_ARCHIVE"\n')
    executable(tools / "sha256sum", checksum + "\n")
    source = BUILDER.read_text()
    marker = 'tar --sort=name --mtime="@$source_epoch"'
    archive_tail = marker + source.rsplit(marker, 1)[1]
    result = subprocess.run(  # noqa: S603 - actual shell tail, synthetic archive tools only.
        ["/bin/bash", "-s"],
        input='set -euo pipefail\narchive="$TEST_ARCHIVE"\nstage="$TEST_STAGE"\nsource_epoch=1\n'
        + archive_tail,
        env={
            **os.environ,
            "PATH": f"{tools}:/usr/bin:/bin",
            "TEST_ARCHIVE": str(tmp_path / "archive.tar.gz"),
            "TEST_STAGE": str(tmp_path),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert "standalone-kit: OK" not in result.stdout


def test_release_console_uses_generic_offline_build_and_keeps_archive_layout(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    repo = tmp_path / "repo"
    (repo / "console/dist").mkdir(parents=True)
    (repo / "console/dist/stale-deployment.txt").write_text("private-build-marker")
    output = tmp_path / "output"
    output.mkdir()
    executable(
        tools / "npm",
        'if [[ "$*" == *"run build:offline" ]]; then '
        'mkdir -p "$TEST_ROOT/console/dist/offline"; '
        'echo generic >"$TEST_ROOT/console/dist/offline/index.html"; '
        'elif [[ "$*" == *"run build" ]]; then '
        'echo "$VITE_OPERATOR_API_BASE_URL" >"$TEST_ROOT/console/dist/index.html"; fi\n',
    )
    segment = BUILDER.read_text().split('echo "-- build Console artifact"', 1)[1]
    segment = segment.split("printf ", 1)[0]
    result = subprocess.run(  # noqa: S603 - actual Console stage with a recording npm boundary.
        ["/bin/bash", "-s"],
        input=(
            'set -euo pipefail\nrepo_root="$TEST_ROOT"\n'
            'release_input="$TEST_OUT"\nsource_epoch=1\n' + segment
        ),
        env={
            **os.environ,
            "PATH": f"{tools}:/usr/bin:/bin",
            "TEST_ROOT": str(repo),
            "TEST_OUT": str(output),
            "VITE_OPERATOR_API_BASE_URL": "https://private-build-marker.example.com",
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    with tarfile.open(output / "console.tar.gz") as archive:
        files = [member.name for member in archive.getmembers() if member.isfile()]
        assert files == ["dist/index.html"]
        assert archive.extractfile(files[0]).read().strip() == b"generic"
