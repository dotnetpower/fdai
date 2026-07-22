"""Regression tests for staged-file repository text gates."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TRANSLATIONS = _ROOT / "scripts/quality/localization/check-translations.sh"
_PUNCTUATION = _ROOT / "scripts/quality/repository/check-punctuation.sh"
_GUIDS = _ROOT / "scripts/quality/repository/check-guids.sh"


def _run(repo: Path, *command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed, test-controlled executables and arguments
        command, cwd=repo, capture_output=True, text=True, check=False
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    result = _run(tmp_path, "git", "init", "--quiet")
    assert result.returncode == 0, result.stderr
    return tmp_path


def test_translation_gate_ignores_untracked_ignored_worktrees(git_repo: Path) -> None:
    source = git_repo / "docs" / "guide.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Guide\n", encoding="utf-8")
    source_sha = _run(git_repo, "git", "hash-object", "docs/guide.md").stdout.strip()
    (git_repo / "docs" / "guide-ko.md").write_text(
        f"---\ntranslation_of: guide.md\ntranslation_source_sha: {source_sha}\n---\n# Guide\n",
        encoding="utf-8",
    )
    (git_repo / ".gitignore").write_text(".improve/\n", encoding="utf-8")
    ignored = git_repo / ".improve" / "worktrees" / "run" / "docs" / "orphan-ko.md"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("ignored\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", ".gitignore", "docs").returncode == 0

    result = _run(git_repo, "bash", str(_TRANSLATIONS))

    assert result.returncode == 0, result.stderr
    assert "1 English docs, 1 translations verified" in result.stdout


def test_text_gates_limit_scans_to_supplied_paths(git_repo: Path) -> None:
    (git_repo / "clean.txt").write_text("clean\n", encoding="utf-8")
    (git_repo / "bad-punctuation.txt").write_text("bad \u2014 punctuation\n", encoding="utf-8")
    bad_guid = "12345678-" + "1234-1234-1234-123456789abc"
    (git_repo / "bad-guid.txt").write_text(f"id={bad_guid}\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", ".").returncode == 0

    punctuation_clean = _run(git_repo, "bash", str(_PUNCTUATION), "clean.txt")
    punctuation_bad = _run(git_repo, "bash", str(_PUNCTUATION), "bad-punctuation.txt")
    guid_clean = _run(git_repo, "bash", str(_GUIDS), "clean.txt")
    guid_bad = _run(git_repo, "bash", str(_GUIDS), "bad-guid.txt")

    assert punctuation_clean.returncode == 0, punctuation_clean.stderr
    assert punctuation_bad.returncode == 1
    assert "bad-punctuation.txt contains" in punctuation_bad.stderr
    assert guid_clean.returncode == 0, guid_clean.stderr
    assert guid_bad.returncode == 1
    assert "bad-guid.txt:1" in guid_bad.stderr


def test_punctuation_baseline_only_allows_the_exact_blob(git_repo: Path) -> None:
    path = git_repo / "legacy.txt"
    path.write_text("legacy \u2026 text\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", "legacy.txt").returncode == 0
    blob_sha = _run(git_repo, "git", "hash-object", "legacy.txt").stdout.strip()
    baseline = git_repo / "scripts" / "quality" / "repository" / "punctuation-baseline.txt"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(f"{blob_sha} legacy.txt", encoding="utf-8")

    unchanged = _run(git_repo, "bash", str(_PUNCTUATION))
    path.write_text("legacy \u2026 text changed\n", encoding="utf-8")
    changed = _run(git_repo, "bash", str(_PUNCTUATION))

    assert unchanged.returncode == 0, unchanged.stderr
    assert "1 baseline blob(s) unchanged" in unchanged.stdout
    assert changed.returncode == 1
    assert "legacy.txt contains" in changed.stderr


def test_pre_commit_scopes_expensive_repository_gates() -> None:
    config = (_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    punctuation = config.split("- id: check-punctuation", 1)[1].split("- id:", 1)[0]
    guids = config.split("- id: check-guids", 1)[1].split("- id:", 1)[0]
    translations = config.split("- id: check-translations", 1)[1].split("- id:", 1)[0]
    core_imports = config.split("- id: check-core-imports", 1)[1].split("- id:", 1)[0]

    assert "pass_filenames: false" not in punctuation
    assert "pass_filenames: false" not in guids
    assert "require_serial: true" in punctuation
    assert "require_serial: true" in guids
    assert "files: ^(README(?:-ko)?\\.md|docs/.*\\.md)$" in translations
    assert "files: ^src/fdai/core/" in core_imports
