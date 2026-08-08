#!/usr/bin/env python3
"""Defer slow external operations until the current commit is validated."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFERRED_EXTERNAL_PATTERNS = (
    re.compile(r"(?:^|\s)gh\s+(?:run|workflow)\b"),
    re.compile(r"(?:^|\s)gh\s+pr\s+checks\b"),
    re.compile(r"(?:^|\s)(?:terraform|tofu)\s+(?:plan|apply|destroy|import|refresh)\b"),
    re.compile(r"(?:^|\s)azd\s+(?:up|deploy|provision)\b"),
    re.compile(
        r"(?:^|\s)(?:docker|podman)\s+"
        r"(?:(?:buildx|compose)\s+build|build|push|pull|compose\s+up\b[^\n]*--build)"
    ),
    re.compile(r"(?:^|\s)az\s+acr\s+build\b"),
    re.compile(r"(?:^|\s)az\s+deployment\s+\S+\s+(?:what-if|validate|create)\b"),
    re.compile(
        r"(?:^|\s)az\s+(?:[A-Za-z0-9_-]+\s+){1,4}"
        r"(?:create|update|delete|start|stop|restart|deallocate|set|invoke|up)\b"
    ),
    re.compile(r"(?:^|\s)(?:bash\s+)?scripts/deployment/(?:azure|release)/\S+"),
)


def _head_has_validation_receipt(repo_root: Path) -> bool:
    completed = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/automation/validation_queue.py"),
            "check-commit",
            "HEAD",
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def enforce_external_operation_order(
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    if tool_name != "run_in_terminal":
        return {"continue": True}
    command = str(tool_input.get("command") or "")
    if not any(pattern.search(command) for pattern in DEFERRED_EXTERNAL_PATTERNS):
        return {"continue": True}
    if _head_has_validation_receipt(repo_root):
        return {"continue": True}
    reason = (
        "Slow external FDAI work must follow completed, tested code. Finish the local slice, run "
        "focused checks, commit it, and obtain a centralized validation receipt before watching "
        "or rerunning GitHub Actions, deploying or provisioning Azure, or building and pushing "
        "container images. Check readiness with "
        "'python3 scripts/automation/validation_queue.py check-commit HEAD'."
    )
    return {
        "systemMessage": reason,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }
