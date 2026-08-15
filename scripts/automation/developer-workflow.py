#!/usr/bin/env python3
"""Report bounded, read-only FDAI developer workflow diagnostics."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.agent.design_context import required_context, required_validation  # noqa: E402

SCHEMA_VERSION = 1
UTC = timezone.utc  # noqa: UP017 - tracked hooks also support system Python 3.10.
MAX_PATHS = 20
MAX_HISTORY_COMMITS = 64
MAX_RECEIPTS = 50
VALIDATION_WARN_SECONDS = 300
PLAYWRIGHT_POOL_SIZE = 10
LOCAL_SERVICE_ENDPOINTS = (
    ("console-frontend", "http://127.0.0.1:5273/"),
    ("operator-api", "http://127.0.0.1:8010/healthz"),
    ("document-ingestion-api", "http://127.0.0.1:8011/healthz"),
    ("document-processing-worker", "http://127.0.0.1:8012/ready"),
    ("isolated-executor", "http://127.0.0.1:8013/ready"),
)
PRESSURE_LIMITS = {
    "cpu_some_avg10": 50.0,
    "io_full_avg10": 5.0,
    "memory_some_avg10": 1.0,
}


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _git_diagnostic(root: Path) -> dict[str, Any]:
    top_level = _git(root, "rev-parse", "--show-toplevel")
    if top_level.returncode != 0:
        return {
            "reason_code": "git_repository_unavailable",
            "status": "unavailable",
        }
    repo_root = Path(top_level.stdout.strip()).resolve()
    head = _git(repo_root, "rev-parse", "--verify", "HEAD^{commit}")
    branch = _git(repo_root, "branch", "--show-current")
    if head.returncode != 0 or branch.returncode != 0:
        return {
            "reason_code": "git_history_unavailable",
            "status": "unavailable",
            "worktree": str(repo_root),
        }
    return {
        "branch": branch.stdout.strip() or "detached",
        "head": head.stdout.strip(),
        "status": "ok",
        "worktree": str(repo_root),
    }


def _index_diagnostic(root: Path) -> dict[str, Any]:
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0:
        return {
            "reason_code": "git_index_unavailable",
            "status": "unavailable",
        }
    staged = 0
    unstaged = 0
    untracked = 0
    overlaps: list[str] = []
    for line in status.stdout.splitlines():
        if len(line) < 4:
            continue
        index_state, worktree_state = line[0], line[1]
        path = line[3:]
        if index_state == "?" and worktree_state == "?":
            untracked += 1
            continue
        staged += int(index_state != " ")
        unstaged += int(worktree_state != " ")
        if index_state != " " and worktree_state != " ":
            overlaps.append(path)
    return {
        "overlap_count": len(overlaps),
        "overlap_paths": overlaps[:MAX_PATHS],
        "staged_count": staged,
        "status": "warning" if overlaps else "ok",
        "unstaged_count": unstaged,
        "untracked_count": untracked,
    }


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _git_common_dir(root: Path) -> tuple[Path, Path] | None:
    top_level = _git(root, "rev-parse", "--show-toplevel")
    if top_level.returncode != 0:
        return None
    repo_root = Path(top_level.stdout.strip()).resolve()
    common = _git(repo_root, "rev-parse", "--git-common-dir")
    if common.returncode != 0:
        return None
    raw = Path(common.stdout.strip())
    return repo_root, (raw if raw.is_absolute() else repo_root / raw).resolve()


def _percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _validation_diagnostic(root: Path) -> dict[str, Any]:
    resolved = _git_common_dir(root)
    if resolved is None:
        return {"reason_code": "validation_repository_unavailable", "status": "unavailable"}
    repo_root, common_dir = resolved
    state_root = common_dir / "fdai-validation-queue"
    pending_dir = state_root / "pending"
    receipts_dir = state_root / "receipts"
    if not pending_dir.is_dir() and not receipts_dir.is_dir():
        return {"reason_code": "validation_state_unavailable", "status": "unavailable"}

    history_result = _git(
        repo_root,
        "rev-list",
        f"--max-count={MAX_HISTORY_COMMITS}",
        "HEAD",
    )
    history = set(history_result.stdout.splitlines()) if history_result.returncode == 0 else set()
    now = datetime.now(UTC)
    pending_ages: list[float] = []
    reachable_pending = 0
    invalid_records = 0
    for path in pending_dir.glob("*.json") if pending_dir.is_dir() else ():
        if path.stem not in history:
            continue
        reachable_pending += 1
        try:
            payload: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            invalid_records += 1
            continue
        enqueued_at = _parse_timestamp(
            payload.get("enqueued_at") if isinstance(payload, dict) else None
        )
        if enqueued_at is None:
            invalid_records += 1
            continue
        pending_ages.append(max(0.0, (now - enqueued_at).total_seconds()))

    receipt_rows: list[tuple[datetime, str]] = []
    for path in receipts_dir.glob("*.json") if receipts_dir.is_dir() else ():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            invalid_records += 1
            continue
        validated_at = _parse_timestamp(
            payload.get("validated_at") if isinstance(payload, dict) else None
        )
        commit = payload.get("commit") if isinstance(payload, dict) else None
        if validated_at is None or not isinstance(commit, str):
            invalid_records += 1
            continue
        receipt_rows.append((validated_at, commit))

    latencies: list[float] = []
    for validated_at, commit in sorted(receipt_rows, reverse=True)[:MAX_RECEIPTS]:
        committed = _git(repo_root, "show", "-s", "--format=%cI", commit)
        committed_at = (
            _parse_timestamp(committed.stdout.strip()) if committed.returncode == 0 else None
        )
        if committed_at is None:
            invalid_records += 1
            continue
        latencies.append(max(0.0, (validated_at - committed_at).total_seconds()))

    oldest_pending = max(pending_ages, default=0.0)
    latency_p95 = _percentile_95(latencies)
    warning = oldest_pending > VALIDATION_WARN_SECONDS or (
        latency_p95 is not None and latency_p95 > VALIDATION_WARN_SECONDS
    )
    return {
        "invalid_record_count": invalid_records,
        "latency_p95_seconds": None if latency_p95 is None else round(latency_p95, 3),
        "oldest_pending_seconds": round(oldest_pending, 3),
        "reachable_pending_count": reachable_pending,
        "receipt_sample_count": len(latencies),
        "status": "warning" if warning else "ok",
    }


def _database_identity(value: str) -> tuple[str, int | None, str] | None:
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return None
    if not parsed.hostname or not parsed.path:
        return None
    return parsed.hostname.lower(), port, parsed.path.removeprefix("/")


def _environment_diagnostic(root: Path) -> dict[str, Any]:
    resolved = _git_common_dir(root)
    if resolved is None:
        return {"reason_code": "environment_repository_unavailable", "status": "unavailable"}
    repo_root, _common_dir = resolved
    reasons: list[str] = []
    python_paths = [
        Path(item).resolve() for item in os.environ.get("PYTHONPATH", "").split(":") if item
    ]
    foreign_python_paths = [
        path
        for path in python_paths
        if path != repo_root and repo_root not in path.parents and "fdai" in path.as_posix().lower()
    ]
    if foreign_python_paths:
        reasons.append("foreign_pythonpath")

    virtual_env = os.environ.get("VIRTUAL_ENV")
    virtual_env_scope = "unset"
    if virtual_env:
        virtual_env_path = Path(virtual_env).resolve()
        virtual_env_scope = (
            "current_worktree"
            if virtual_env_path == repo_root or repo_root in virtual_env_path.parents
            else "foreign"
        )
        if virtual_env_scope == "foreign":
            reasons.append("foreign_virtual_env")

    database_url = os.environ.get("FDAI_DATABASE_URL", "")
    runtime_dsn = os.environ.get("FDAI_STATE_STORE_DSN", "")
    database_collision = False
    if database_url and runtime_dsn:
        test_identity = _database_identity(database_url)
        runtime_identity = _database_identity(runtime_dsn)
        database_collision = test_identity is not None and test_identity == runtime_identity
        if database_collision:
            reasons.append("runtime_database_collision")

    return {
        "database_identity_collision": database_collision,
        "foreign_pythonpath_count": len(foreign_python_paths),
        "reason_codes": reasons,
        "runtime_variable_count": sum(name.startswith("FDAI_") for name in os.environ),
        "status": "warning" if reasons else "ok",
        "virtual_env_scope": virtual_env_scope,
    }


def _hook_diagnostic(root: Path) -> dict[str, Any]:
    resolved = _git_common_dir(root)
    if resolved is None:
        return {"reason_code": "hook_repository_unavailable", "status": "unavailable"}
    repo_root, _common_dir = resolved
    index = _index_diagnostic(repo_root)
    if index["status"] == "unavailable":
        return {"reason_code": "hook_index_unavailable", "status": "unavailable"}
    hooks_path_result = _git(repo_root, "config", "--get", "core.hooksPath")
    hooks_path = hooks_path_result.stdout.strip() if hooks_path_result.returncode == 0 else ""
    reasons: list[str] = []
    if hooks_path != ".githooks":
        reasons.append("repository_hooks_not_installed")
    overlap_paths = index["overlap_paths"]
    if index["overlap_count"]:
        reasons.append("staged_unstaged_overlap")
    manifest_paths = {
        "security/integrity/manifest.json",
        "security/integrity/manifest.json.sig",
    }
    if any(path in manifest_paths for path in overlap_paths):
        reasons.append("integrity_manifest_overlap")
    return {
        "hooks_path_status": "ok" if hooks_path == ".githooks" else "missing",
        "overlap_count": index["overlap_count"],
        "reason_codes": reasons,
        "recovery_codes": [
            code
            for code, applies in (
                ("install_repository_hooks", hooks_path != ".githooks"),
                ("restage_complete_paths", bool(index["overlap_count"])),
                (
                    "preserve_manifest_before_resign",
                    "integrity_manifest_overlap" in reasons,
                ),
            )
            if applies
        ],
        "status": "warning" if reasons else "ok",
    }


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _browser_runner_diagnostic(
    lock_root: Path | None = None,
    *,
    is_alive: Any = _process_is_alive,
) -> dict[str, Any]:
    root = lock_root or Path(tempfile.gettempdir()) / f"fdai-playwright-port-pool-{os.getuid()}"
    held = 0
    stale = 0
    invalid = 0
    for slot in range(PLAYWRIGHT_POOL_SIZE):
        owner_path = root / f"slot-{slot}" / "owner.json"
        if not owner_path.is_file():
            continue
        try:
            if owner_path.stat().st_size > 4_096:
                raise ValueError
            owner: object = json.loads(owner_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            invalid += 1
            continue
        pid = owner.get("pid") if isinstance(owner, dict) else None
        if not isinstance(pid, int) or pid <= 0:
            invalid += 1
        elif is_alive(pid):
            held += 1
        else:
            stale += 1
    available = PLAYWRIGHT_POOL_SIZE - held - stale - invalid
    return {
        "available_slots": max(0, available),
        "held_slots": held,
        "invalid_slots": invalid,
        "stale_slots": stale,
        "status": "warning" if available == 0 or invalid or stale else "ok",
        "total_slots": PLAYWRIGHT_POOL_SIZE,
    }


def _http_ready(url: str) -> bool:
    request = Request(url, method="GET")  # noqa: S310 - endpoints are fixed loopback URLs.
    try:
        with urlopen(request, timeout=0.5) as response:  # noqa: S310
            return 200 <= response.status < 300
    except OSError:
        return False


def _local_services_diagnostic(
    root: Path,
    *,
    probe: Any = _http_ready,
    process_lines: list[str] | None = None,
) -> dict[str, Any]:
    resolved = _git_common_dir(root)
    if resolved is None:
        return {"reason_code": "service_repository_unavailable", "status": "unavailable"}
    repo_root, _common_dir = resolved
    if not (repo_root / ".fdai").is_dir():
        return {"reason_code": "local_stack_not_prepared", "status": "unavailable"}
    services = [{"name": name, "ready": bool(probe(url))} for name, url in LOCAL_SERVICE_ENDPOINTS]
    if process_lines is None:
        process_result = subprocess.run(  # noqa: S603 - fixed process inventory command.
            ["ps", "-eo", "args="],  # noqa: S607 - ps is the fixed local executable.
            capture_output=True,
            text=True,
            check=False,
        )
        process_lines = process_result.stdout.splitlines() if process_result.returncode == 0 else []
    core_ready = any(" -m fdai" in line and "pytest" not in line for line in process_lines)
    services.insert(0, {"name": "core-runtime", "ready": core_ready})
    unavailable = [str(service["name"]) for service in services if not service["ready"]]
    return {
        "ready_count": len(services) - len(unavailable),
        "service_count": len(services),
        "services": services,
        "status": "warning" if unavailable else "ok",
        "unavailable_services": unavailable,
    }


def _pressure_avg10(path: Path, category: str) -> float | None:
    try:
        if path.stat().st_size > 4_096:
            return None
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(rf"^{re.escape(category)}\s+avg10=([0-9.]+)", content, re.MULTILINE)
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _run_code_status() -> subprocess.CompletedProcess[str] | None:
    executable = shutil.which("code")
    if executable is None:
        return None
    try:
        return subprocess.run(  # noqa: S603 - resolved VS Code executable and fixed arguments.
            [executable, "--status"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _editor_pressure_diagnostic(
    proc_root: Path = Path("/proc"),
    *,
    code_status: Any = _run_code_status,
) -> dict[str, Any]:
    pressure = {
        "cpu_some_avg10": _pressure_avg10(proc_root / "pressure" / "cpu", "some"),
        "io_full_avg10": _pressure_avg10(proc_root / "pressure" / "io", "full"),
        "memory_some_avg10": _pressure_avg10(proc_root / "pressure" / "memory", "some"),
    }
    exceeded = [
        name
        for name, value in pressure.items()
        if value is not None and value >= PRESSURE_LIMITS[name]
    ]
    code_result = code_status()
    if code_result is None or code_result.returncode != 0:
        client_status = "unavailable"
        extension_host_count = 0
    else:
        client_status = "ok"
        extension_host_count = sum(
            "extension-host" in line.lower()
            for line in (code_result.stdout + code_result.stderr).splitlines()[:200]
        )
    return {
        "browser_tool_payload": "upstream_bounded_by_cli_first_workflow",
        "client_status": client_status,
        "extension_host_count": extension_host_count,
        "host_pressure_exceeded": exceeded,
        "pressure": pressure,
        "status": "warning" if exceeded else "ok",
    }


def _editor_pressure_for_root(root: Path) -> dict[str, Any]:
    resolved = _git_common_dir(root)
    if resolved is None:
        return {"reason_code": "editor_repository_unavailable", "status": "unavailable"}
    repo_root, _common_dir = resolved
    if not (repo_root / ".fdai").is_dir():
        return {"reason_code": "local_workspace_not_prepared", "status": "unavailable"}
    return _editor_pressure_diagnostic()


def status_report(root: Path) -> dict[str, Any]:
    """Build one versioned report without changing repository or process state."""
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "schema_version": SCHEMA_VERSION,
        "sections": {
            "browser_runner": _browser_runner_diagnostic(),
            "editor_pressure": _editor_pressure_for_root(root),
            "environment": _environment_diagnostic(root),
            "git": _git_diagnostic(root),
            "hooks": _hook_diagnostic(root),
            "index": _index_diagnostic(root),
            "local_services": _local_services_diagnostic(root),
            "validation": _validation_diagnostic(root),
        },
    }


def preflight_report(root: Path) -> dict[str, Any]:
    """Return the diagnostics that must be clean before a focused check."""
    sections = {
        "environment": _environment_diagnostic(root),
        "git": _git_diagnostic(root),
        "hooks": _hook_diagnostic(root),
        "index": _index_diagnostic(root),
    }
    return {
        "read_only": True,
        "schema_version": SCHEMA_VERSION,
        "sections": sections,
        "status": (
            "ok"
            if all(section.get("status") == "ok" for section in sections.values())
            else "blocked"
        ),
    }


def _relative_targets(root: Path, targets: list[str]) -> tuple[str, ...] | None:
    resolved = _git_common_dir(root)
    if resolved is None:
        return None
    repo_root, _common_dir = resolved
    relative: set[str] = set()
    for raw in targets:
        candidate = Path(raw)
        absolute = candidate if candidate.is_absolute() else repo_root / candidate
        try:
            relative.add(absolute.resolve().relative_to(repo_root).as_posix())
        except ValueError:
            return None
    return tuple(sorted(relative))


def context_plan_report(root: Path, targets: list[str]) -> dict[str, Any]:
    """Resolve current context and focused checks without recording a design read."""
    relative = _relative_targets(root, targets)
    if relative is None:
        return {
            "read_only": True,
            "reason_code": "context_target_outside_repository",
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
        }
    return {
        "focused_checks": list(required_validation(relative)),
        "read_only": True,
        "required_documents": list(required_context(relative)),
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "targets": list(relative),
    }


def resume_report(root: Path) -> dict[str, Any]:
    """Load the official handover JSON without duplicating its history selection."""
    script = REPO_ROOT / "scripts" / "automation" / "session-handover.py"
    completed = subprocess.run(  # noqa: S603 - fixed repository script and arguments.
        [sys.executable, str(script), "show", "--json"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "read_only": True,
            "reason_code": "handover_command_failed",
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
        }
    try:
        payload: object = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict):
        return {
            "read_only": True,
            "reason_code": "handover_output_invalid",
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
        }
    return {"read_only": True, **payload}


def _render_text(report: dict[str, Any]) -> str:
    git_state = report["sections"]["git"]
    if git_state["status"] != "ok":
        return f"developer-workflow: unavailable ({git_state['reason_code']})"
    index_state = report["sections"]["index"]
    return (
        "developer-workflow: ok\n"
        f"  worktree: {git_state['worktree']}\n"
        f"  branch:   {git_state['branch']}\n"
        f"  head:     {git_state['head'][:12]}\n"
        f"  index:    {index_state['status']} "
        f"(staged={index_state['staged_count']}, unstaged={index_state['unstaged_count']}, "
        f"untracked={index_state['untracked_count']}, overlap={index_state['overlap_count']})"
    )


def _render_context_plan(report: dict[str, Any]) -> str:
    if report["status"] != "ok":
        return f"developer-workflow: unavailable ({report['reason_code']})"
    lines = ["developer-workflow: context plan"]
    lines.extend(f"  read:  {path}" for path in report["required_documents"])
    lines.extend(f"  check: {command}" for command in report["focused_checks"])
    return "\n".join(lines)


def _render_resume(report: dict[str, Any]) -> str:
    if report["status"] == "unavailable":
        return f"developer-workflow: unavailable ({report['reason_code']})"
    return (
        "developer-workflow: resume\n"
        f"  commit:     {str(report['commit'])[:12]}\n"
        f"  validation: {'validated' if report['validated'] else 'pending'}\n"
        f"  relation:   {report['history_relation']}\n"
        f"  next:       {report['next_action']}"
    )


def _render_preflight(report: dict[str, Any]) -> str:
    lines = [f"developer-workflow: preflight {report['status']}"]
    for name, section in report["sections"].items():
        lines.append(f"  {name}: {section['status']}")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--json", action="store_true", dest="as_json")
    context_parser = subparsers.add_parser("context-plan")
    context_parser.add_argument("targets", nargs="+")
    context_parser.add_argument("--json", action="store_true", dest="as_json")
    resume_parser = subparsers.add_parser("resume")
    resume_parser.add_argument("--json", action="store_true", dest="as_json")
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "context-plan":
        report = context_plan_report(Path.cwd(), arguments.targets)
        renderer = _render_context_plan
    elif arguments.command == "resume":
        report = resume_report(Path.cwd())
        renderer = _render_resume
    elif arguments.command == "preflight":
        report = preflight_report(Path.cwd())
        renderer = _render_preflight
    else:
        report = status_report(Path.cwd())
        renderer = _render_text
    if arguments.as_json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(renderer(report))
    return 1 if arguments.command == "preflight" and report["status"] != "ok" else 0


if __name__ == "__main__":
    raise SystemExit(main())
