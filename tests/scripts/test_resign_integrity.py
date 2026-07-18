"""Regression tests for automatic framework-surface re-signing."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _REPO_ROOT / "scripts" / "integrity" / "resign-if-surface-staged.sh"
_SURFACE_LIST = _REPO_ROOT / "scripts" / "lib" / "framework-surface.txt"
_BASH = shutil.which("bash") or "bash"
_GIT = shutil.which("git") or "git"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed binary, test-controlled arguments
        [_GIT, *args], cwd=repo, check=True, capture_output=True, text=True
    )


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
    surface_list = root / "scripts" / "lib" / "framework-surface.txt"
    surface_list.parent.mkdir(parents=True)
    shutil.copy2(_SURFACE_LIST, surface_list)

    signer = root / "scripts" / "integrity" / "sign-integrity.sh"
    signer.write_text(
        "#!/usr/bin/env bash\n"
        "touch signer-called\n"
        "printf '{}\\n' > security/integrity/manifest.json\n"
        "printf 'signature\\n' > security/integrity/manifest.json.sig\n",
        encoding="utf-8",
    )
    signer.chmod(0o755)

    integrity_dir = root / "security" / "integrity"
    integrity_dir.mkdir(parents=True)
    (integrity_dir / "manifest.json").write_text("{}\n", encoding="utf-8")
    (integrity_dir / "manifest.json.sig").write_text("signature\n", encoding="utf-8")
    private_key = root / "private-key.pem"
    private_key.write_text("test-only\n", encoding="utf-8")

    protected = root / "src" / "fdai" / "core" / "example.py"
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
    (repo / "src" / "fdai" / "core" / "example.py").unlink()
    _git(repo, "add", "-u")

    result = _run_hook(repo)

    assert result.returncode == 0, result.stderr
    assert (repo / "signer-called").exists()


def test_partially_staged_protected_file_blocks_resigning(repo: Path) -> None:
    protected = repo / "src" / "fdai" / "core" / "example.py"
    protected.write_text("VALUE = 2\n", encoding="utf-8")
    _git(repo, "add", str(protected.relative_to(repo)))
    protected.write_text("VALUE = 3\n", encoding="utf-8")

    result = _run_hook(repo)

    assert result.returncode == 1
    assert "also has unstaged changes" in result.stderr
    assert not (repo / "signer-called").exists()


def test_partially_staged_unprotected_file_does_not_block_resigning(repo: Path) -> None:
    protected = repo / "src" / "fdai" / "core" / "example.py"
    protected.write_text("VALUE = 2\n", encoding="utf-8")
    ordinary = repo / "notes.txt"
    ordinary.write_text("staged\n", encoding="utf-8")
    _git(repo, "add", str(protected.relative_to(repo)), str(ordinary.relative_to(repo)))
    ordinary.write_text("unstaged\n", encoding="utf-8")

    result = _run_hook(repo)

    assert result.returncode == 0, result.stderr
    assert (repo / "signer-called").exists()
