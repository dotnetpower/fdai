"""Regression tests for automatic framework-surface re-signing."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HOOK = _REPO_ROOT / "scripts" / "integrity" / "resign-if-surface-staged.sh"
_GENERATOR = _REPO_ROOT / "scripts" / "integrity" / "gen-integrity-manifest.py"
_PRE_COMMIT_HOOK = _REPO_ROOT / ".githooks" / "pre-commit"
_PRE_COMMIT_CONFIG = _REPO_ROOT / ".pre-commit-config.yaml"
_SURFACE_LIST = _REPO_ROOT / "scripts" / "lib" / "framework-surface.txt"
_BASH = shutil.which("bash") or "bash"
_GIT = shutil.which("git") or "git"
_PROTECTED_FILE = Path("services/core-control-plane/src/fdai/core/example.py")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed binary, test-controlled arguments
        [_GIT, *args], cwd=repo, check=True, capture_output=True, text=True
    )


def _git_output(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed binary, test-controlled arguments
        [_GIT, *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "integrity-tests@example.com")
    _git(root, "config", "user.name", "integrity-tests")

    hook = root / "scripts" / "integrity" / _HOOK.name
    hook.parent.mkdir(parents=True)
    shutil.copy2(_HOOK, hook)
    shutil.copy2(_GENERATOR, hook.parent / _GENERATOR.name)
    surface_list = root / "scripts" / "lib" / "framework-surface.txt"
    surface_list.parent.mkdir(parents=True)
    shutil.copy2(_SURFACE_LIST, surface_list)

    signer = root / "scripts" / "integrity" / "sign-integrity.sh"
    signer.write_text(
        "#!/usr/bin/env bash\n"
        "touch signer-called\n"
        "printf '{}\\n' > \"${FDAI_INTEGRITY_MANIFEST_OUT:?}\"\n"
        "printf 'signature\\n' > \"${FDAI_INTEGRITY_SIGNATURE_OUT:?}\"\n",
        encoding="utf-8",
    )
    signer.chmod(0o755)

    integrity_dir = root / "security" / "integrity"
    integrity_dir.mkdir(parents=True)
    (integrity_dir / "manifest.json").write_text("{}\n", encoding="utf-8")
    (integrity_dir / "manifest.json.sig").write_text("signature\n", encoding="utf-8")
    private_key = root / "private-key.pem"
    private_key.write_text("test-only\n", encoding="utf-8")

    protected = root / _PROTECTED_FILE
    protected.parent.mkdir(parents=True)
    protected.write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    return root


def _run_hook(repo: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "FDAI_INTEGRITY_KEY": str(repo / "private-key.pem")}
    return subprocess.run(  # noqa: S603 - fixed binary and hook path
        [_BASH, str(repo / "scripts" / "integrity" / _HOOK.name)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_staged_protected_deletion_triggers_resigning(repo: Path) -> None:
    (repo / _PROTECTED_FILE).unlink()
    _git(repo, "add", "-u")

    result = _run_hook(repo)

    assert result.returncode == 0, result.stderr
    assert (repo / "signer-called").exists()


def test_partially_staged_protected_file_signs_index_content(repo: Path) -> None:
    protected = repo / _PROTECTED_FILE
    protected.write_text("VALUE = 2\n", encoding="utf-8")
    _git(repo, "add", str(protected.relative_to(repo)))
    protected.write_text("VALUE = 3\n", encoding="utf-8")

    result = _run_hook(repo)

    assert result.returncode == 0, result.stderr
    assert (repo / "signer-called").exists()
    assert protected.read_text(encoding="utf-8") == "VALUE = 3\n"
    assert _git_output(repo, "show", f":{_PROTECTED_FILE}") == "VALUE = 2\n"


def test_partially_staged_unprotected_file_does_not_block_resigning(repo: Path) -> None:
    protected = repo / _PROTECTED_FILE
    protected.write_text("VALUE = 2\n", encoding="utf-8")
    ordinary = repo / "notes.txt"
    ordinary.write_text("staged\n", encoding="utf-8")
    _git(repo, "add", str(protected.relative_to(repo)), str(ordinary.relative_to(repo)))
    ordinary.write_text("unstaged\n", encoding="utf-8")

    result = _run_hook(repo)

    assert result.returncode == 0, result.stderr
    assert (repo / "signer-called").exists()


def test_unstaged_integrity_worktree_changes_are_preserved(repo: Path) -> None:
    manifest = repo / "security" / "integrity" / "manifest.json"
    signature = repo / "security" / "integrity" / "manifest.json.sig"
    manifest.write_text('{"worktree": "preserve"}\n', encoding="utf-8")
    signature.write_text("worktree-signature\n", encoding="utf-8")
    protected = repo / _PROTECTED_FILE
    protected.write_text("VALUE = 2\n", encoding="utf-8")
    _git(repo, "add", str(protected.relative_to(repo)))

    result = _run_hook(repo)

    assert result.returncode == 0, result.stderr
    assert manifest.read_text(encoding="utf-8") == '{"worktree": "preserve"}\n'
    assert signature.read_text(encoding="utf-8") == "worktree-signature\n"
    assert _git_output(repo, "show", ":security/integrity/manifest.json") == "{}\n"
    assert _git_output(repo, "show", ":security/integrity/manifest.json.sig") == "signature\n"


def test_manifest_generator_hashes_staged_content(repo: Path) -> None:
    protected = repo / _PROTECTED_FILE
    protected.write_text("VALUE = 2\n", encoding="utf-8")
    _git(repo, "add", str(protected.relative_to(repo)))
    protected.write_text("VALUE = 3\n", encoding="utf-8")
    output = repo / "index-manifest.json"

    result = subprocess.run(  # noqa: S603 - fixed interpreter and test-controlled script
        [
            sys.executable,
            str(repo / "scripts" / "integrity" / _GENERATOR.name),
            "--source",
            "index",
            "--out",
            str(output),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["files"][str(_PROTECTED_FILE)] == hashlib.sha256(b"VALUE = 2\n").hexdigest()


def test_index_manifest_generation_preserves_existing_timestamp(repo: Path) -> None:
    manifest_path = repo / "security" / "integrity" / "manifest.json"
    manifest_path.write_text('{"generated_at": "2026-08-27T00:00:00Z"}\n', encoding="utf-8")
    _git(repo, "add", str(manifest_path.relative_to(repo)))
    output = repo / "index-manifest.json"

    result = subprocess.run(  # noqa: S603 - fixed interpreter and test-controlled script
        [
            sys.executable,
            str(repo / "scripts" / "integrity" / _GENERATOR.name),
            "--source",
            "index",
            "--out",
            str(output),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    generated = json.loads(output.read_text(encoding="utf-8"))
    assert generated["generated_at"] == "2026-08-27T00:00:00Z"


def test_tracked_pre_commit_prepares_index_before_quality_framework() -> None:
    hook = _PRE_COMMIT_HOOK.read_text(encoding="utf-8")
    signing = "bash scripts/integrity/resign-if-surface-staged.sh"
    quality = "exec uv run pre-commit run --hook-stage pre-commit"

    assert signing in hook
    assert quality in hook
    assert hook.index(signing) < hook.index(quality)
    assert "id: resign-integrity" not in _PRE_COMMIT_CONFIG.read_text(encoding="utf-8")
