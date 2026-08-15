"""Contracts for bounded developer workflow diagnostics."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "automation" / "developer-workflow.py"
UTC = timezone.utc  # noqa: UP017 - test remains compatible with system Python 3.10.


def _run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed repository script with test-owned arguments.
        [sys.executable, str(SCRIPT), *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed Git arguments against a temporary repository.
        ["git", *arguments],  # noqa: S607 - Git is the fixed test executable.
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_status_json_is_versioned_and_read_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "--quiet", "--initial-branch=main").returncode == 0
    assert _git(repo, "config", "user.email", "user@example.com").returncode == 0
    assert _git(repo, "config", "user.name", "Example User").returncode == 0
    (repo / "example.txt").write_text("value\n", encoding="utf-8")
    assert _git(repo, "add", "example.txt").returncode == 0
    assert _git(repo, "commit", "--quiet", "-m", "initial").returncode == 0
    before = _git(repo, "status", "--porcelain").stdout

    result = _run(repo, "status", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["read_only"] is True
    assert payload["sections"]["git"]["status"] == "ok"
    assert payload["sections"]["git"]["branch"] == "main"
    after = _git(repo, "status", "--porcelain").stdout
    assert after == before


def test_status_reports_non_repository_as_unavailable(tmp_path: Path) -> None:
    result = _run(tmp_path, "status", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["sections"]["git"] == {
        "reason_code": "git_repository_unavailable",
        "status": "unavailable",
    }
    assert payload["sections"]["index"] == {
        "reason_code": "git_index_unavailable",
        "status": "unavailable",
    }


def test_status_reports_staged_and_unstaged_overlap(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "--quiet", "--initial-branch=main").returncode == 0
    assert _git(repo, "config", "user.email", "user@example.com").returncode == 0
    assert _git(repo, "config", "user.name", "Example User").returncode == 0
    tracked = repo / "tracked.txt"
    tracked.write_text("initial\n", encoding="utf-8")
    assert _git(repo, "add", "tracked.txt").returncode == 0
    assert _git(repo, "commit", "--quiet", "-m", "initial").returncode == 0
    tracked.write_text("staged\n", encoding="utf-8")
    assert _git(repo, "add", "tracked.txt").returncode == 0
    tracked.write_text("unstaged\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("new\n", encoding="utf-8")

    result = _run(repo, "status", "--json")

    assert result.returncode == 0, result.stderr
    index = json.loads(result.stdout)["sections"]["index"]
    assert index == {
        "overlap_count": 1,
        "overlap_paths": ["tracked.txt"],
        "staged_count": 1,
        "status": "warning",
        "unstaged_count": 1,
        "untracked_count": 1,
    }


def test_status_reports_validation_age_and_recent_latency(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "--quiet", "--initial-branch=main").returncode == 0
    assert _git(repo, "config", "user.email", "user@example.com").returncode == 0
    assert _git(repo, "config", "user.name", "Example User").returncode == 0
    tracked = repo / "tracked.txt"
    tracked.write_text("first\n", encoding="utf-8")
    assert _git(repo, "add", "tracked.txt").returncode == 0
    assert _git(repo, "commit", "--quiet", "-m", "first").returncode == 0
    validated_commit = _git(repo, "rev-parse", "HEAD").stdout.strip()
    committed_at = datetime.fromisoformat(
        _git(repo, "show", "-s", "--format=%cI", validated_commit).stdout.strip()
    )
    tracked.write_text("second\n", encoding="utf-8")
    assert _git(repo, "add", "tracked.txt").returncode == 0
    assert _git(repo, "commit", "--quiet", "-m", "second").returncode == 0
    pending_commit = _git(repo, "rev-parse", "HEAD").stdout.strip()
    state = repo / ".git" / "fdai-validation-queue"
    pending = state / "pending"
    receipts = state / "receipts"
    pending.mkdir(parents=True)
    receipts.mkdir()
    (pending / f"{pending_commit}.json").write_text(
        json.dumps(
            {
                "commit": pending_commit,
                "enqueued_at": (datetime.now(UTC) - timedelta(minutes=10)).isoformat(),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (receipts / f"{validated_commit}.json").write_text(
        json.dumps(
            {
                "commit": validated_commit,
                "validated_at": (committed_at + timedelta(seconds=120)).isoformat(),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run(repo, "status", "--json")

    assert result.returncode == 0, result.stderr
    validation = json.loads(result.stdout)["sections"]["validation"]
    assert validation["status"] == "warning"
    assert validation["reachable_pending_count"] == 1
    assert validation["oldest_pending_seconds"] >= 599
    assert validation["receipt_sample_count"] == 1
    assert validation["latency_p95_seconds"] == 120
    assert validation["invalid_record_count"] == 0


def test_context_plan_is_deduplicated_and_rejects_external_targets(tmp_path: Path) -> None:
    result = _run(
        SCRIPT.parents[2],
        "context-plan",
        "scripts/automation/session-handover.py",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["targets"] == ["scripts/automation/session-handover.py"]
    assert payload["required_documents"] == sorted(set(payload["required_documents"]))
    assert ".github/copilot-instructions.md" in payload["required_documents"]
    assert "scripts/verify.sh" in payload["focused_checks"]

    external = _run(
        SCRIPT.parents[2],
        "context-plan",
        str(tmp_path.parent / "outside.py"),
        "--json",
    )
    assert external.returncode == 0, external.stderr
    assert json.loads(external.stdout)["reason_code"] == "context_target_outside_repository"


def test_resume_uses_official_handover_json(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "--quiet", "--initial-branch=main").returncode == 0
    assert _git(repo, "config", "user.email", "user@example.com").returncode == 0
    assert _git(repo, "config", "user.name", "Example User").returncode == 0
    (repo / "example.txt").write_text("value\n", encoding="utf-8")
    assert _git(repo, "add", "example.txt").returncode == 0
    assert _git(repo, "commit", "--quiet", "-m", "initial").returncode == 0
    recorded = subprocess.run(  # noqa: S603 - fixed repository script and temporary repo.
        [
            sys.executable,
            str(SCRIPT.parents[2] / "scripts/automation/session-handover.py"),
            "record",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert recorded.returncode == 0, recorded.stderr

    result = _run(repo, "resume", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["read_only"] is True
    assert payload["status"] == "ok"
    assert payload["validated"] is False
    assert payload["next_action"] == "wait_for_integration_validation"
