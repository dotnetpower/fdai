#!/usr/bin/env python3
"""Validate the repository issue creation and completion contract."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
FORM_DIR = REPO_ROOT / ".github/ISSUE_TEMPLATE"
FORM_PATH = FORM_DIR / "work-item.yml"
CONFIG_PATH = REPO_ROOT / ".github/ISSUE_TEMPLATE/config.yml"
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/issue-lifecycle.yml"
INSTRUCTIONS_PATH = REPO_ROOT / ".github/copilot-instructions.md"
CONTRIBUTING_PATH = REPO_ROOT / "CONTRIBUTING.md"
HELPER_PATH = REPO_ROOT / "scripts/automation/project-board.py"
HELPER_SUPPORT_PATH = REPO_ROOT / "scripts/automation/project_board_support.py"


def _mapping(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.relative_to(REPO_ROOT)} MUST contain a YAML mapping")
    return loaded


def validate() -> list[str]:
    errors: list[str] = []
    for path in (
        FORM_PATH,
        CONFIG_PATH,
        WORKFLOW_PATH,
        INSTRUCTIONS_PATH,
        CONTRIBUTING_PATH,
        HELPER_PATH,
        HELPER_SUPPORT_PATH,
    ):
        if not path.is_file():
            errors.append(f"missing required issue lifecycle file: {path.relative_to(REPO_ROOT)}")
    if errors:
        return errors

    for form_path in sorted(FORM_DIR.glob("*.yml")):
        if form_path.name == "config.yml":
            continue
        form = _mapping(form_path)
        body = form.get("body")
        fields = body if isinstance(body, list) else []
        exit_fields = [
            field
            for field in fields
            if isinstance(field, dict) and field.get("id") == "exit_criteria"
        ]
        if len(exit_fields) != 1:
            errors.append(f"{form_path.name} MUST define exactly one exit_criteria field")
            continue
        field = exit_fields[0]
        validations = field.get("validations")
        required = validations.get("required") if isinstance(validations, dict) else None
        if field.get("type") != "textarea" or required is not True:
            errors.append(f"{form_path.name} exit_criteria MUST be a required textarea")
        placeholder = field.get("attributes", {}).get("placeholder", "")
        if "- [ ]" not in str(placeholder):
            errors.append(f"{form_path.name} exit_criteria MUST demonstrate checkbox syntax")

    config = _mapping(CONFIG_PATH)
    if config.get("blank_issues_enabled") is not False:
        errors.append("blank issues MUST stay disabled so Exit criteria cannot be bypassed")

    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow_tokens = (
        "types: [opened, edited, labeled, unlabeled, reopened, closed]",
        "issues: write",
        'label = "needs-exit-criteria"',
        'labels: ["needs-triage"]',
        'name.startsWith("type:")',
        'name.startsWith("priority:")',
        'name.startsWith("area:")',
        'removeLabel("completed")',
        "completionMarker",
        "hasUnchecked",
        'state: "open"',
        'labels: ["completed"]',
    )
    for token in workflow_tokens:
        if token not in workflow:
            errors.append(f"issue-lifecycle.yml missing contract token: {token}")

    instructions = INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    for token in (
        "## Issue Lifecycle (MUST)",
        "Exit criteria",
        "`completed`",
        "Project updates are best-effort",
        "WIP limit of two applies",
    ):
        if token not in instructions:
            errors.append(f"copilot-instructions.md missing issue rule: {token}")

    contributing = CONTRIBUTING_PATH.read_text(encoding="utf-8")
    for token in (
        "needs-exit-criteria",
        "Residual work keeps the issue open",
        "completed",
        "### Non-blocking board operation",
        "project-board.py start",
        "Never call the helper from pre-commit",
    ):
        if token not in contributing:
            errors.append(f"CONTRIBUTING.md missing issue procedure: {token}")

    helper = HELPER_PATH.read_text(encoding="utf-8")
    for token in ("def start", "def sync", "sync deferred", "--strict"):
        if token not in helper:
            errors.append(f"project-board.py missing non-blocking contract: {token}")
    helper_support = HELPER_SUPPORT_PATH.read_text(encoding="utf-8")
    for token in ("def desired_status", "class GitHubClient", "def has_exit_contract"):
        if token not in helper_support:
            errors.append(f"project_board_support.py missing board policy: {token}")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"issue-lifecycle: ERROR: {error}", file=sys.stderr)
        return 1
    print("issue-lifecycle: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
