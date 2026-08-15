"""Contracts for automatic local coding-session handovers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "automation" / "session-handover.py"
POST_COMMIT = REPO_ROOT / ".githooks" / "post-commit"
RESUME = REPO_ROOT / "scripts" / "automation" / "resume.sh"


def _run(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed test commands and temporary paths
        list(arguments),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_record_and_show_include_validation_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _run(repo, "git", "init", "--quiet", "--initial-branch=main").returncode == 0
    assert _run(repo, "git", "config", "user.email", "user@example.com").returncode == 0
    assert _run(repo, "git", "config", "user.name", "Example User").returncode == 0
    (repo / "example.txt").write_text("value\n", encoding="utf-8")
    assert _run(repo, "git", "add", "example.txt").returncode == 0
    assert _run(repo, "git", "commit", "--quiet", "-m", "feat(example): add value").returncode == 0
    commit = _run(repo, "git", "rev-parse", "HEAD").stdout.strip()

    recorded = _run(repo, "python3", str(SCRIPT), "record", commit)
    pending = _run(repo, "python3", str(SCRIPT), "show")

    assert recorded.returncode == 0, recorded.stderr
    assert pending.returncode == 0, pending.stderr
    common = Path(_run(repo, "git", "rev-parse", "--git-common-dir").stdout.strip())
    state = repo / common / "fdai-handovers"
    payload = json.loads((state / "latest.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["commit"] == commit
    assert payload["changed_files"] == ["example.txt"]
    assert payload["subject"] == "feat(example): add value"
    assert "validation: pending" in pending.stdout

    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    json_result = _run(repo, "python3", str(SCRIPT), "show", "--json")
    report = json.loads(json_result.stdout)
    assert report["history_relation"] == "reachable"
    assert report["current_worktree_status"]["changed_count"] == 1
    assert report["next_action"] == "wait_for_integration_validation"

    receipts = repo / common / "fdai-validation-queue" / "receipts"
    receipts.mkdir(parents=True)
    (receipts / f"{commit}.json").write_text("{}\n", encoding="utf-8")
    validated = _run(repo, "python3", str(SCRIPT), "show")

    assert validated.returncode == 0, validated.stderr
    assert "validation: validated" in validated.stdout


def test_hooks_and_resume_invoke_handover_tool() -> None:
    post_commit = POST_COMMIT.read_text(encoding="utf-8")
    resume = RESUME.read_text(encoding="utf-8")

    assert 'python3 "$handover_script" record HEAD' in post_commit
    assert "python3 scripts/automation/session-handover.py show" in resume
