#!/usr/bin/env python3
"""Validate the repository issue creation and completion contract."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
FORM_PATH = REPO_ROOT / ".github/ISSUE_TEMPLATE/work-item.yml"
CONFIG_PATH = REPO_ROOT / ".github/ISSUE_TEMPLATE/config.yml"
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/issue-lifecycle.yml"
INSTRUCTIONS_PATH = REPO_ROOT / ".github/copilot-instructions.md"
CONTRIBUTING_PATH = REPO_ROOT / "CONTRIBUTING.md"


def _mapping(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.relative_to(REPO_ROOT)} MUST contain a YAML mapping")
    return loaded


def validate() -> list[str]:
    errors: list[str] = []
    for path in (FORM_PATH, CONFIG_PATH, WORKFLOW_PATH, INSTRUCTIONS_PATH, CONTRIBUTING_PATH):
        if not path.is_file():
            errors.append(f"missing required issue lifecycle file: {path.relative_to(REPO_ROOT)}")
    if errors:
        return errors

    form = _mapping(FORM_PATH)
    body = form.get("body")
    fields = body if isinstance(body, list) else []
    exit_fields = [
        field for field in fields if isinstance(field, dict) and field.get("id") == "exit_criteria"
    ]
    if len(exit_fields) != 1:
        errors.append("work-item.yml MUST define exactly one exit_criteria field")
    else:
        field = exit_fields[0]
        validations = field.get("validations")
        required = validations.get("required") if isinstance(validations, dict) else None
        if field.get("type") != "textarea" or required is not True:
            errors.append("exit_criteria MUST be a required textarea")
        placeholder = field.get("attributes", {}).get("placeholder", "")
        if "- [ ]" not in str(placeholder):
            errors.append("exit_criteria placeholder MUST demonstrate checkbox syntax")

    config = _mapping(CONFIG_PATH)
    if config.get("blank_issues_enabled") is not False:
        errors.append("blank issues MUST stay disabled so Exit criteria cannot be bypassed")

    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow_tokens = (
        "types: [opened, edited, reopened, closed]",
        "issues: write",
        'label = "needs-exit-criteria"',
        'removeLabel("completed")',
        "hasUnchecked",
        'state: "open"',
        'labels: ["completed"]',
    )
    for token in workflow_tokens:
        if token not in workflow:
            errors.append(f"issue-lifecycle.yml missing contract token: {token}")

    instructions = INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    for token in ("## Issue Lifecycle (MUST)", "Exit criteria", "`completed`"):
        if token not in instructions:
            errors.append(f"copilot-instructions.md missing issue rule: {token}")

    contributing = CONTRIBUTING_PATH.read_text(encoding="utf-8")
    for token in ("needs-exit-criteria", "Residual work keeps the issue open", "completed"):
        if token not in contributing:
            errors.append(f"CONTRIBUTING.md missing issue procedure: {token}")
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
