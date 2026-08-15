#!/usr/bin/env python3
# ruff: noqa: E402 - direct execution bootstraps the repository package root before imports.
"""Report bounded, read-only FDAI developer workflow diagnostics."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.agent.design_context import required_context, required_validation  # noqa: E402
from scripts.automation.developer_workflow_repository import (  # noqa: E402
    environment_diagnostic as _environment_diagnostic,
)
from scripts.automation.developer_workflow_repository import (
    git_common_dir as _git_common_dir,
)
from scripts.automation.developer_workflow_repository import (
    git_diagnostic as _git_diagnostic,
)
from scripts.automation.developer_workflow_repository import (
    hook_diagnostic as _hook_diagnostic,
)
from scripts.automation.developer_workflow_repository import (
    index_diagnostic as _index_diagnostic,
)
from scripts.automation.developer_workflow_repository import (
    validation_diagnostic as _validation_diagnostic,
)
from scripts.automation.developer_workflow_runtime import (  # noqa: E402
    browser_runner_diagnostic as _browser_runner_diagnostic,
)
from scripts.automation.developer_workflow_runtime import (
    editor_pressure_diagnostic as _editor_pressure_diagnostic,
)
from scripts.automation.developer_workflow_runtime import (
    editor_pressure_for_root as _editor_pressure_for_root,
)
from scripts.automation.developer_workflow_runtime import (
    local_services_diagnostic as _local_services_diagnostic,
)

SCHEMA_VERSION = 1
UTC = timezone.utc  # noqa: UP017 - tracked hooks also support system Python 3.10.
__all__ = [
    "_browser_runner_diagnostic",
    "_editor_pressure_diagnostic",
    "_local_services_diagnostic",
    "main",
]


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
