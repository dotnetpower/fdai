from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/quality/repository/check-reference-only-sources.py"


def _git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - test-controlled Git arguments.
        ["git", *arguments],  # noqa: S607 - repository test invokes Git from PATH.
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def snapshot_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "--quiet").returncode == 0
    snapshot = repo / "rule-catalog/sources/restricted-source/revision"
    snapshot.mkdir(parents=True)
    (snapshot / "SNAPSHOT.json").write_text(
        json.dumps(
            {
                "source_id": "restricted-source",
                "redistribution": "reference-only",
                "content_sha256": "0" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return repo


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed checker with a test-owned root.
        [sys.executable, str(SCRIPT), "--root", str(repo), "--cached"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_reference_only_snapshot_rejects_staged_source_body(snapshot_repo: Path) -> None:
    snapshot = snapshot_repo / "rule-catalog/sources/restricted-source/revision"
    tree = snapshot / "tree"
    tree.mkdir()
    (tree / "synthetic-control.txt").write_text(
        "Synthetic restricted control body.\n",
        encoding="utf-8",
    )
    assert _git(snapshot_repo, "add", ".").returncode == 0

    result = _run(snapshot_repo)

    assert result.returncode == 1
    assert "reference-only snapshot contains source body" in result.stderr
    assert "synthetic-control.txt" in result.stderr


def test_reference_only_provenance_without_body_passes(snapshot_repo: Path) -> None:
    assert _git(snapshot_repo, "add", ".").returncode == 0

    result = _run(snapshot_repo)

    assert result.returncode == 0, result.stderr
    assert "OK (1 snapshot(s), 0 source body file(s))" in result.stdout


def test_embeddable_snapshot_body_passes(snapshot_repo: Path) -> None:
    snapshot = snapshot_repo / "rule-catalog/sources/restricted-source/revision"
    manifest = snapshot / "SNAPSHOT.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["redistribution"] = "embeddable"
    manifest.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    tree = snapshot / "tree"
    tree.mkdir()
    (tree / "public-control.txt").write_text("Synthetic public control.\n", encoding="utf-8")
    assert _git(snapshot_repo, "add", ".").returncode == 0

    result = _run(snapshot_repo)

    assert result.returncode == 0, result.stderr
    assert "OK (1 snapshot(s), 1 source body file(s))" in result.stdout


def test_checker_is_wired_into_ci_and_local_gates() -> None:
    command = "scripts/quality/repository/check-reference-only-sources.py"
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    verify = (REPO_ROOT / "scripts/verify.sh").read_text(encoding="utf-8")
    pre_commit = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    assert f"uv run python {command}" in workflow
    assert f"uv run python {command}" in verify
    assert f"python3 {command} --cached" in pre_commit
