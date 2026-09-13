"""Verify source pins with real local Git and synthetic files, without live effects."""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from tests.integration.scripts.test_standalone_kit_release_guards import (
    BUILDER,
    bounded_environment,
    bounded_prelude,
    executable,
)

ROOT = Path(__file__).resolve().parents[3]
RELEASE = ROOT / "scripts/deployment/release"


def git(repo, *args):
    executable = shutil.which("git")
    assert executable is not None
    result = subprocess.run(  # noqa: S603 - synthetic local Git repository operations only.
        [executable, *args],
        cwd=repo,
        env={
            **{key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "user@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "user@example.com",
        },
        capture_output=True,
        check=True,
        timeout=15,
    )
    return result.stdout.decode().strip()


def commit_repository(repo):
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Synthetic release input", "--", ".")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def source_module(monkeypatch):
    monkeypatch.syspath_prepend(str(RELEASE))
    return importlib.import_module("release_source")


@pytest.fixture
def source_repo(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    (repo / ".gitignore").write_text("ignored/\n")
    (repo / "service.py").write_text("VALUE = 1\n")
    (repo / "uv.lock").write_text("version = 1\n")
    return repo, commit_repository(repo)


def test_unchanged_source_has_a_stable_pin(source_module, source_repo):
    repo, commit = source_repo
    pin = source_module.require_source(repo, commit)
    assert len(pin) == 64
    assert source_module.require_source(repo, commit, pin) == pin


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_raw_blob_check_detects_hidden_git_changes(source_module, source_repo, flag):
    repo, commit = source_repo
    pin = source_module.require_source(repo, commit)
    git(repo, "update-index", flag, "service.py")
    (repo / "service.py").write_text("VALUE = 2\n")
    assert git(repo, "status", "--porcelain") == ""
    with pytest.raises(source_module.SourceDriftError, match="bytes differ"):
        source_module.require_source(repo, commit, pin)


def test_edit_then_restore_cannot_reuse_a_source_pin(source_module, source_repo):
    repo, commit = source_repo
    pin = source_module.require_source(repo, commit)
    path = repo / "service.py"
    original, details = path.read_bytes(), path.stat()
    path.write_text("VALUE = 2\n")
    path.write_bytes(original)
    os.utime(path, ns=(details.st_atime_ns, details.st_mtime_ns))
    assert git(repo, "status", "--porcelain") == ""
    with pytest.raises(source_module.SourceDriftError, match="changed during assembly"):
        source_module.require_source(repo, commit, pin)


def test_new_head_is_not_relabelled_as_the_previous_source(source_module, source_repo):
    repo, commit = source_repo
    git(repo, "commit", "--allow-empty", "-qm", "Synthetic new revision", "--", ".")
    with pytest.raises(source_module.SourceDriftError, match="revision changed"):
        source_module.require_source(repo, commit)


def test_detached_build_source_excludes_local_ignored_files(source_module, source_repo, tmp_path):
    repo, commit = source_repo
    (repo / "ignored").mkdir()
    (repo / "ignored/deployment.env").write_text("SYNTHETIC_PRIVATE_VALUE=not-a-build-input\n")
    snapshot = tmp_path / "build-source"
    git(repo, "worktree", "add", "--detach", str(snapshot), commit)
    pin = source_module.require_source(snapshot, commit)
    (repo / "service.py").write_text("VALUE = 2\n")
    assert not (snapshot / "ignored").exists()
    assert (snapshot / "service.py").read_text() == "VALUE = 1\n"
    assert source_module.require_source(snapshot, commit, pin) == pin


@pytest.mark.parametrize("replacement", ["fifo", "symlink", "mode"])
def test_file_boundary_rejects_unexpected_types_without_blocking(
    source_module, source_repo, replacement
):
    repo, commit = source_repo
    path = repo / "service.py"
    git(repo, "update-index", "--skip-worktree", "service.py")
    if replacement == "mode":
        path.chmod(0o755)
    else:
        path.unlink()
        if replacement == "fifo":
            os.mkfifo(path)
        else:
            path.symlink_to("uv.lock")
    with pytest.raises((source_module.SourceDriftError, OSError)):
        source_module.require_source(repo, commit)


def test_committed_internal_document_link_is_supported(source_module, source_repo):
    repo, _commit = source_repo
    (repo / "link").symlink_to("service.py")
    commit = commit_repository(repo)
    pin = source_module.require_source(repo, commit)
    assert source_module.require_source(repo, commit, pin) == pin


def test_cli_redacts_private_failure_values(source_module, source_repo, monkeypatch, capsys):
    repo, commit = source_repo

    def fail(*_args):
        raise OSError("synthetic-private-path")

    monkeypatch.setattr(source_module, "require_source", fail)
    assert source_module.main(["--repo-root", str(repo), "--source-commit", commit]) == 3
    output = capsys.readouterr()
    assert not output.out
    assert "synthetic-private-path" not in output.err


@pytest.mark.parametrize("drift", [False, True])
def test_staging_fences_source_immediately_before_signing(source_module, source_repo, drift):
    repo, _commit = source_repo
    target = repo / "scripts/deployment/release/release_source.py"
    target.parent.mkdir(parents=True)
    target.write_bytes((RELEASE / "release_source.py").read_bytes())
    commit = commit_repository(repo)
    fingerprint = source_module.require_source(repo, commit)
    if drift:
        (repo / "service.py").write_text("VALUE = 2\n")
    shell = (RELEASE / "stage-offline-kit.sh").read_text()
    boundary = (
        "source_boundary() {"
        + shell.split("source_boundary() {", 1)[1].split("\nSAFE_WRITER=", 1)[0]
    )
    before_sign = shell.rsplit('echo "-- sign kit"', 1)[0]
    assert before_sign.rstrip().endswith("source_boundary")
    result = subprocess.run(  # noqa: S603 - actual shell source boundary; signing is a sentinel.
        ["/bin/bash", "-s"],
        cwd=repo,
        input="set -euo pipefail\n" + boundary + '\nsource_boundary\necho "signing-reached"\n',
        env={
            **os.environ,
            "PYTHON": sys.executable,
            "repo_root": str(repo),
            "SOURCE_COMMIT": commit,
            "SOURCE_FINGERPRINT": fingerprint,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert (result.returncode != 0) is drift
    assert ("signing-reached" not in result.stdout) is drift


def test_complete_builder_creates_a_private_pinned_source_and_scoped_environment(
    source_module, source_repo, tmp_path
):
    repo, _commit = source_repo
    (repo / ".gitignore").write_text("ignored/\n.venv/\n__pycache__/\n")
    for relative in (
        "scripts/deployment/release/workdir-guard.py",
        "scripts/deployment/release/release_source.py",
        "scripts/automation/run-bounded-command.py",
    ):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes())
    commit = commit_repository(repo)
    (repo / "ignored").mkdir()
    (repo / "ignored/deployment.env").write_text("SYNTHETIC_PRIVATE_VALUE=excluded\n")
    tools = tmp_path / "tools"
    executable(
        tools / "uv",
        '[[ "$*" == *"--offline --frozen"* ]] || exit 65\n'
        'mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"\n'
        'ln -s "$TEST_PYTHON" "$UV_PROJECT_ENVIRONMENT/bin/python"\n',
    )
    out = tmp_path / "release"
    unowned_environment = tmp_path / "other-session-env"
    segment = BUILDER.read_text().split('source_commit="', 1)[1].split('cli_version="', 1)[0]
    result = subprocess.run(  # noqa: S603 - actual checkout boundary with a local uv recorder.
        ["/bin/bash", "-s"],
        cwd=repo,
        input=bounded_prelude()
        + 'repo_root="$TEST_REPO"\nout="$TEST_OUT"\nsource_commit="'
        + segment,
        env={
            **bounded_environment(),
            "PATH": f"{tools}:{os.environ['PATH']}",
            "TEST_REPO": str(repo),
            "TEST_OUT": str(out),
            "UV_PROJECT_ENVIRONMENT": str(unowned_environment),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert not unowned_environment.exists()
    assert not (out / "source/ignored").exists()
    assert (out / "source/.venv/bin/python").is_file()
    assert len(source_module.require_source(out / "source", commit)) == 64
