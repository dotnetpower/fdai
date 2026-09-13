#!/usr/bin/env python3
"""Claim GitHub issue reviews with a normalized hostname label."""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import Any

LABEL_PREFIX = "inprogress:"
LABEL_COLOR = "FBCA04"
MAX_LABEL_LENGTH = 50


class WorkerLabelError(RuntimeError):
    """Report an invalid worker identity or unavailable GitHub boundary."""


def _run(arguments: Sequence[str], *, timeout: float = 30) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - executable and arguments are repository-owned.
            list(arguments),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WorkerLabelError(str(error)) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise WorkerLabelError(detail)
    return result.stdout


def repository_name(configured: str | None) -> str:
    """Return an explicit repository or the current GitHub repository name."""
    if configured:
        return configured
    value = _run(("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"))
    repository = value.strip()
    if "/" not in repository:
        raise WorkerLabelError("unable to resolve the current GitHub repository")
    return repository


def label_for_hostname(hostname: str | None = None) -> str:
    """Return a stable GitHub label for a local hostname."""
    raw = (hostname if hostname is not None else socket.gethostname()).strip().lower()
    normalized = re.sub(r"[^a-z0-9._-]+", "-", raw)
    normalized = re.sub(r"-+", "-", normalized).strip(".-_")
    normalized = normalized[: MAX_LABEL_LENGTH - len(LABEL_PREFIX)].rstrip(".-_")
    if not normalized:
        raise WorkerLabelError("hostname does not contain a valid label identity")
    return f"{LABEL_PREFIX}{normalized}"


def _label_names(raw: object) -> frozenset[str]:
    values = raw if isinstance(raw, list) else []
    return frozenset(
        str(value["name"])
        for value in values
        if isinstance(value, Mapping) and isinstance(value.get("name"), str)
    )


def issue_labels(repository: str, issue_number: int) -> frozenset[str]:
    """Return the current labels for one issue."""
    output = _run(
        (
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--repo",
            repository,
            "--json",
            "labels",
        )
    )
    try:
        raw: Any = json.loads(output)
    except json.JSONDecodeError as error:
        raise WorkerLabelError(f"invalid JSON from gh: {error}") from error
    if not isinstance(raw, dict):
        raise WorkerLabelError("gh issue view did not return a JSON object")
    return _label_names(raw.get("labels"))


def _foreign_worker_labels(labels: frozenset[str], current: str) -> list[str]:
    return sorted(label for label in labels if label.startswith(LABEL_PREFIX) and label != current)


def _ensure_label(repository: str, label: str) -> None:
    _run(
        (
            "gh",
            "label",
            "create",
            label,
            "--repo",
            repository,
            "--color",
            LABEL_COLOR,
            "--description",
            "Issue review currently claimed by this worker.",
            "--force",
        )
    )


def claim(repository: str, issue_numbers: Sequence[int], *, hostname: str | None = None) -> str:
    """Claim issues for this worker, rejecting an existing foreign claim."""
    label = label_for_hostname(hostname)
    labels_by_issue = {
        issue_number: issue_labels(repository, issue_number) for issue_number in issue_numbers
    }
    for issue_number, labels in labels_by_issue.items():
        foreign = _foreign_worker_labels(labels, label)
        if foreign:
            raise WorkerLabelError(
                f"issue #{issue_number} is already claimed by {', '.join(foreign)}"
            )

    pending = [
        issue_number for issue_number, labels in labels_by_issue.items() if label not in labels
    ]
    if pending:
        _ensure_label(repository, label)
    for issue_number in pending:
        _run(
            (
                "gh",
                "issue",
                "edit",
                str(issue_number),
                "--repo",
                repository,
                "--add-label",
                label,
            )
        )
        final_labels = issue_labels(repository, issue_number)
        if label not in final_labels or _foreign_worker_labels(final_labels, label):
            raise WorkerLabelError(f"unable to verify worker claim for issue #{issue_number}")
    return label


def release(repository: str, issue_numbers: Sequence[int], *, hostname: str | None = None) -> str:
    """Remove only this worker's claim label from the supplied issues."""
    label = label_for_hostname(hostname)
    failures: list[str] = []
    for issue_number in issue_numbers:
        try:
            if label not in issue_labels(repository, issue_number):
                continue
            _run(
                (
                    "gh",
                    "issue",
                    "edit",
                    str(issue_number),
                    "--repo",
                    repository,
                    "--remove-label",
                    label,
                )
            )
            if label in issue_labels(repository, issue_number):
                raise WorkerLabelError(f"unable to verify worker release for issue #{issue_number}")
        except WorkerLabelError as error:
            failures.append(f"issue #{issue_number}: {error}")
    if failures:
        raise WorkerLabelError("; ".join(failures))
    return label


def parser() -> argparse.ArgumentParser:
    """Build the command-line contract for issue worker labels."""
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--repo", help="GitHub OWNER/REPO; defaults to the current repository")
    commands = value.add_subparsers(dest="command", required=True)
    for command in ("claim", "release"):
        command_parser = commands.add_parser(command)
        command_parser.add_argument("issue_numbers", type=int, nargs="+")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    """Run one worker-label operation and return a shell-friendly status."""
    args = parser().parse_args(argv)
    try:
        repository = repository_name(args.repo)
        operation = claim if args.command == "claim" else release
        label = operation(repository, args.issue_numbers)
        print(f"issue-worker-label: {args.command} label={label}")
        return 0
    except WorkerLabelError as error:
        print(f"issue-worker-label: ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
