from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/quality/localization/check-derived-sources.py"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - test-controlled Git arguments.
        ["git", *args],  # noqa: S607 - repository test invokes Git from PATH.
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def docs_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "--quiet").returncode == 0
    assert _git(repo, "config", "user.email", "test@example.com").returncode == 0
    assert _git(repo, "config", "user.name", "Test User").returncode == 0
    source = repo / "docs/roadmap/architecture/source.md"
    catalog_source = repo / "services/example/catalog-source.txt"
    guide = repo / "docs/user-guide/guide.md"
    source.parent.mkdir(parents=True)
    catalog_source.parent.mkdir(parents=True)
    guide.parent.mkdir(parents=True)
    source.write_text("# Source\n", encoding="utf-8")
    catalog_source.write_text("# Catalog source\n", encoding="utf-8")
    source_sha = _git(repo, "hash-object", str(source)).stdout.strip()
    catalog_source_sha = _git(repo, "hash-object", str(catalog_source)).stdout.strip()
    guide.write_text(
        "---\n"
        "derives_from:\n"
        "  - source: docs/roadmap/architecture/source.md\n"
        f"    sha: {source_sha}\n"
        "---\n"
        "# Guide\n",
        encoding="utf-8",
    )
    catalog = (
        repo / "services/system-knowledge-service/src/"
        "fdai_system_knowledge_service/data/catalog.json"
    )
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        json.dumps(
            {
                "source_revision": "0" * 40,
                "records": [
                    {
                        "sources": [
                            {
                                "path": "services/example/catalog-source.txt",
                                "blob_sha": catalog_source_sha,
                            }
                        ]
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert _git(repo, "add", ".").returncode == 0
    assert _git(repo, "commit", "--quiet", "-m", "initial").returncode == 0
    source_revision = _git(repo, "rev-parse", "HEAD").stdout.strip()
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    payload["source_revision"] = source_revision
    catalog.write_text(json.dumps(payload), encoding="utf-8")
    assert _git(repo, "add", str(catalog)).returncode == 0
    assert _git(repo, "commit", "--quiet", "-m", "catalog provenance").returncode == 0
    assert _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD").returncode == 0
    return repo


def test_cached_mode_checks_the_staged_source_blob(docs_repo: Path) -> None:
    source = docs_repo / "docs/roadmap/architecture/source.md"
    source.write_text("# Staged source\n", encoding="utf-8")
    assert _git(docs_repo, "add", str(source)).returncode == 0
    staged_sha = _git(docs_repo, "rev-parse", ":docs/roadmap/architecture/source.md").stdout.strip()
    source.write_text("# Unstaged source\n", encoding="utf-8")

    result = subprocess.run(  # noqa: S603 - fixed repository script.
        [sys.executable, str(SCRIPT), "--cached"],
        cwd=docs_repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert f"current={staged_sha}" in result.stderr
    assert _git(docs_repo, "hash-object", str(source)).stdout.strip() not in result.stderr


def test_cached_mode_ignores_unstaged_source_changes(docs_repo: Path) -> None:
    source = docs_repo / "docs/roadmap/architecture/source.md"
    source.write_text("# Unstaged source\n", encoding="utf-8")

    result = subprocess.run(  # noqa: S603 - fixed repository script.
        [sys.executable, str(SCRIPT), "--cached"],
        cwd=docs_repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "OK (1 doc(s) pinned" in result.stdout


def test_cached_mode_checks_staged_system_catalog_source(docs_repo: Path) -> None:
    source = docs_repo / "services/example/catalog-source.txt"
    source.write_text("# Changed catalog source\n", encoding="utf-8")
    assert _git(docs_repo, "add", str(source)).returncode == 0

    result = subprocess.run(  # noqa: S603 - fixed repository script.
        [sys.executable, str(SCRIPT), "--cached"],
        cwd=docs_repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "stale System Knowledge catalog source" in result.stderr
    assert "catalog-source.txt" in result.stderr


def test_cached_mode_accepts_staged_system_catalog_refresh(docs_repo: Path) -> None:
    source = docs_repo / "services/example/catalog-source.txt"
    source.write_text("# Changed catalog source\n", encoding="utf-8")
    assert _git(docs_repo, "add", str(source)).returncode == 0
    staged_sha = _git(
        docs_repo,
        "rev-parse",
        ":services/example/catalog-source.txt",
    ).stdout.strip()
    catalog = (
        docs_repo / "services/system-knowledge-service/src/"
        "fdai_system_knowledge_service/data/catalog.json"
    )
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    payload["records"][0]["sources"][0]["blob_sha"] = staged_sha
    catalog.write_text(json.dumps(payload), encoding="utf-8")
    assert _git(docs_repo, "add", str(catalog)).returncode == 0
    source.write_text("# Unstaged catalog source\n", encoding="utf-8")

    result = subprocess.run(  # noqa: S603 - fixed repository script.
        [sys.executable, str(SCRIPT), "--cached"],
        cwd=docs_repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "1 System Knowledge source(s) pinned" in result.stdout


def test_cached_mode_rejects_side_branch_catalog_revision(docs_repo: Path) -> None:
    side_file = docs_repo / "side.txt"
    side_file.write_text("side branch\n", encoding="utf-8")
    assert _git(docs_repo, "add", str(side_file)).returncode == 0
    assert _git(docs_repo, "commit", "--quiet", "-m", "side branch").returncode == 0
    side_revision = _git(docs_repo, "rev-parse", "HEAD").stdout.strip()
    catalog = (
        docs_repo / "services/system-knowledge-service/src/"
        "fdai_system_knowledge_service/data/catalog.json"
    )
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    payload["source_revision"] = side_revision
    catalog.write_text(json.dumps(payload), encoding="utf-8")
    assert _git(docs_repo, "add", str(catalog)).returncode == 0

    result = subprocess.run(  # noqa: S603 - fixed repository script.
        [sys.executable, str(SCRIPT), "--cached"],
        cwd=docs_repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "is not an ancestor of protected main" in result.stderr


def test_changed_only_skips_unrelated_staged_path(docs_repo: Path) -> None:
    unrelated = docs_repo / "console/src/app.tsx"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("export {};\n", encoding="utf-8")
    assert _git(docs_repo, "add", str(unrelated)).returncode == 0

    result = subprocess.run(  # noqa: S603 - fixed repository script.
        [sys.executable, str(SCRIPT), "--cached", "--changed-only"],
        cwd=docs_repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "check-derived-sources: SKIP (no staged owning inputs).\n"


def test_changed_only_checks_catalog_source_from_current_catalog(docs_repo: Path) -> None:
    source = docs_repo / "services/example/catalog-source.txt"
    source.write_text("# Changed catalog source\n", encoding="utf-8")
    assert _git(docs_repo, "add", str(source)).returncode == 0

    result = subprocess.run(  # noqa: S603 - fixed repository script.
        [sys.executable, str(SCRIPT), "--cached", "--changed-only"],
        cwd=docs_repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "stale System Knowledge catalog source" in result.stderr


def test_pre_commit_runs_cached_derived_source_check() -> None:
    config = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    hook = config.split("- id: check-derived-sources", 1)[1].split("- id:", 1)[0]

    assert "check-derived-sources.py --cached --changed-only" in hook
    assert "pass_filenames: false" in hook
    assert "always_run: true" in hook
    assert "files:" not in hook
