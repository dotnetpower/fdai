"""Behavioral tests for ``scripts/integrity/check-protected-paths.sh``.

The guard warns (upstream) or hard-blocks (fork) when a change touches the
framework surface. These tests drive the script through a throwaway git repo
so the mode logic, the exact-file-match rule, the CI-override refusal, and the
fail-loud path are all pinned against regressions. The final test is a drift
guard: it asserts the script's ``protected_prefixes`` list stays covered by
``.github/CODEOWNERS`` (the two are separate sources of truth for the same
surface and must not diverge).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "integrity" / "check-protected-paths.sh"
_SURFACE_LIST = _REPO_ROOT / "scripts" / "lib" / "framework-surface.txt"
_CODEOWNERS = _REPO_ROOT / ".github" / "CODEOWNERS"

_RANGE = "HEAD~1...HEAD"
_GIT = shutil.which("git") or "git"
_BASH = shutil.which("bash") or "bash"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - full path via shutil.which, fixed argv
        [_GIT, *args], cwd=cwd, check=True, capture_output=True, text=True
    )


def _run(repo: Path, rng: str, **env_extra: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    # Neutralize any inherited fork signals; each test sets what it needs.
    for key in ("FDAI_FORK", "FDAI_ALLOW_PROTECTED", "GITHUB_ACTIONS"):
        env.pop(key, None)
    env.update(env_extra)
    return subprocess.run(  # noqa: S603 - full path via shutil.which, fixed argv
        [_BASH, str(_SCRIPT), rng],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def _commit_edit(repo: Path, rel: str, body: str, msg: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", msg)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    # Base commit: one protected file + one ordinary fork-owned file.
    (root / "src" / "fdai" / "core").mkdir(parents=True)
    (root / "src" / "fdai" / "core" / "loop.py").write_text("x = 1\n")
    (root / "fork").mkdir()
    (root / "fork" / "adapter.py").write_text("y = 1\n")
    surface_target = root / "scripts" / "lib" / "framework-surface.txt"
    surface_target.parent.mkdir(parents=True)
    shutil.copy2(_SURFACE_LIST, surface_target)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def test_upstream_protected_edit_is_advisory(repo: Path) -> None:
    _commit_edit(repo, "src/fdai/core/loop.py", "x = 2\n", "edit core")
    res = _run(repo, _RANGE)
    assert res.returncode == 0, res.stderr
    assert "FRAMEWORK SURFACE" in res.stderr


def test_fork_protected_edit_is_blocked(repo: Path) -> None:
    _commit_edit(repo, "src/fdai/core/loop.py", "x = 2\n", "edit core")
    res = _run(repo, _RANGE, FDAI_FORK="1")
    assert res.returncode == 1
    assert "BLOCKED" in res.stderr


def test_non_protected_edit_passes_both_modes(repo: Path) -> None:
    _commit_edit(repo, "fork/adapter.py", "y = 2\n", "edit fork adapter")
    assert _run(repo, _RANGE).returncode == 0
    assert _run(repo, _RANGE, FDAI_FORK="1").returncode == 0


def test_local_override_unblocks_fork(repo: Path) -> None:
    _commit_edit(repo, "src/fdai/core/loop.py", "x = 2\n", "edit core")
    res = _run(repo, _RANGE, FDAI_FORK="1", FDAI_ALLOW_PROTECTED="1")
    assert res.returncode == 0


def test_override_is_ignored_in_ci(repo: Path) -> None:
    _commit_edit(repo, "src/fdai/core/loop.py", "x = 2\n", "edit core")
    res = _run(
        repo,
        _RANGE,
        FDAI_FORK="1",
        FDAI_ALLOW_PROTECTED="1",
        GITHUB_ACTIONS="true",
    )
    assert res.returncode == 1
    assert "IGNORED in CI" in res.stderr


def test_bad_range_fails_loud(repo: Path) -> None:
    res = _run(repo, "nonexistent-ref-xyz...HEAD")
    assert res.returncode == 2


def test_exact_file_match_not_prefix(repo: Path) -> None:
    # `composition.py` is protected as an exact file; a sibling `.bak` is not.
    _commit_edit(repo, "src/fdai/composition.py.bak", "z = 1\n", "add bak")
    res = _run(repo, _RANGE, FDAI_FORK="1")
    assert res.returncode == 0


def _script_prefixes() -> list[str]:
    prefixes = []
    for raw in _SURFACE_LIST.read_text().splitlines():
        value = re.sub(r"#.*$", "", raw).strip()
        if value:
            prefixes.append(value)
    return prefixes


def test_codeowners_covers_every_protected_prefix() -> None:
    prefixes = _script_prefixes()
    assert prefixes, "expected a non-empty protected-prefix list"
    owned = {
        line.split()[0]
        for line in _CODEOWNERS.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing = [p for p in prefixes if f"/{p}" not in owned]
    assert not missing, f"CODEOWNERS missing framework-surface paths: {missing}"
