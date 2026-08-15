"""Contracts for bounded developer workflow diagnostics."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "automation" / "developer-workflow.py"
UTC = timezone.utc  # noqa: UP017 - test remains compatible with system Python 3.10.


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("developer_workflow", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(
    root: Path,
    *arguments: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed repository script with test-owned arguments.
        [sys.executable, str(SCRIPT), *arguments],
        cwd=root,
        capture_output=True,
        env={**os.environ, **(env or {})},
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


def test_preflight_blocks_environment_contamination_without_echoing_secrets(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "--quiet", "--initial-branch=main").returncode == 0
    assert _git(repo, "config", "user.email", "user@example.com").returncode == 0
    assert _git(repo, "config", "user.name", "Example User").returncode == 0
    (repo / "example.txt").write_text("value\n", encoding="utf-8")
    assert _git(repo, "add", "example.txt").returncode == 0
    assert _git(repo, "commit", "--quiet", "-m", "initial").returncode == 0
    secret = "do-not-print"
    database = f"postgresql+psycopg://user:{secret}@localhost:5432/runtime"

    result = _run(
        repo,
        "preflight",
        "--json",
        env={
            "FDAI_DATABASE_URL": database,
            "FDAI_STATE_STORE_DSN": database,
            "PYTHONPATH": str(tmp_path / "other-fdai-worktree" / "src"),
            "VIRTUAL_ENV": str(tmp_path / "other-fdai-worktree" / ".venv"),
        },
    )

    assert result.returncode == 1
    assert secret not in result.stdout
    environment = json.loads(result.stdout)["sections"]["environment"]
    assert environment["status"] == "warning"
    assert environment["database_identity_collision"] is True
    assert environment["foreign_pythonpath_count"] == 1
    assert environment["virtual_env_scope"] == "foreign"
    assert environment["reason_codes"] == [
        "foreign_pythonpath",
        "foreign_virtual_env",
        "runtime_database_collision",
    ]


def test_status_classifies_integrity_manifest_hook_overlap(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "--quiet", "--initial-branch=main").returncode == 0
    assert _git(repo, "config", "user.email", "user@example.com").returncode == 0
    assert _git(repo, "config", "user.name", "Example User").returncode == 0
    assert _git(repo, "config", "core.hooksPath", ".githooks").returncode == 0
    manifest = repo / "security" / "integrity" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"version":1}\n', encoding="utf-8")
    assert _git(repo, "add", "security/integrity/manifest.json").returncode == 0
    assert _git(repo, "commit", "--quiet", "-m", "initial").returncode == 0
    manifest.write_text('{"version":2}\n', encoding="utf-8")
    assert _git(repo, "add", "security/integrity/manifest.json").returncode == 0
    manifest.write_text('{"version":3}\n', encoding="utf-8")
    before = _git(repo, "status", "--porcelain").stdout

    result = _run(repo, "status", "--json")

    assert result.returncode == 0, result.stderr
    hooks = json.loads(result.stdout)["sections"]["hooks"]
    assert hooks == {
        "hooks_path_status": "ok",
        "overlap_count": 1,
        "reason_codes": ["staged_unstaged_overlap", "integrity_manifest_overlap"],
        "recovery_codes": ["restage_complete_paths", "preserve_manifest_before_resign"],
        "status": "warning",
    }
    assert _git(repo, "status", "--porcelain").stdout == before


def test_browser_runner_reports_held_stale_and_invalid_slots(tmp_path: Path) -> None:
    module = _load_module()
    lock_root = tmp_path / "port-pool"
    for slot, payload in (
        (0, {"pid": 10}),
        (1, {"pid": 20}),
        (2, {"pid": "invalid"}),
    ):
        owner = lock_root / f"slot-{slot}" / "owner.json"
        owner.parent.mkdir(parents=True)
        owner.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    result = module._browser_runner_diagnostic(lock_root, is_alive=lambda pid: pid == 10)

    assert result == {
        "available_slots": 7,
        "held_slots": 1,
        "invalid_slots": 1,
        "stale_slots": 1,
        "status": "warning",
        "total_slots": 10,
    }


def test_local_services_report_each_unavailable_owner(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "--quiet", "--initial-branch=main").returncode == 0
    assert _git(repo, "config", "user.email", "user@example.com").returncode == 0
    assert _git(repo, "config", "user.name", "Example User").returncode == 0
    (repo / "example.txt").write_text("value\n", encoding="utf-8")
    assert _git(repo, "add", "example.txt").returncode == 0
    assert _git(repo, "commit", "--quiet", "-m", "initial").returncode == 0
    (repo / ".fdai").mkdir()

    result = module._local_services_diagnostic(
        repo,
        probe=lambda url: not url.endswith(("8011/healthz", "8013/ready")),
        process_lines=[".venv/bin/python -m fdai"],
    )

    assert result["status"] == "warning"
    assert result["service_count"] == 6
    assert result["ready_count"] == 4
    assert result["unavailable_services"] == [
        "document-ingestion-api",
        "isolated-executor",
    ]


def test_editor_pressure_separates_host_and_client_state(tmp_path: Path) -> None:
    module = _load_module()
    pressure = tmp_path / "pressure"
    pressure.mkdir()
    (pressure / "cpu").write_text(
        "some avg10=75.00 avg60=20.00 avg300=10.00 total=1\nfull avg10=0.00 total=0\n",
        encoding="utf-8",
    )
    (pressure / "io").write_text(
        "some avg10=0.00 total=0\nfull avg10=0.25 avg60=0.10 total=1\n",
        encoding="utf-8",
    )
    (pressure / "memory").write_text(
        "some avg10=0.00 total=0\nfull avg10=0.00 total=0\n",
        encoding="utf-8",
    )
    code_result = subprocess.CompletedProcess(
        args=["code", "--status"],
        returncode=0,
        stdout="extension-host one\nextension-host two\n",
        stderr="",
    )

    result = module._editor_pressure_diagnostic(
        tmp_path,
        code_status=lambda: code_result,
    )

    assert result["status"] == "warning"
    assert result["host_pressure_exceeded"] == ["cpu_some_avg10"]
    assert result["client_status"] == "ok"
    assert result["extension_host_count"] == 2
    assert result["browser_tool_payload"] == "upstream_bounded_by_cli_first_workflow"
