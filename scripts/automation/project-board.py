#!/usr/bin/env python3
"""Start and reconcile FDAI GitHub Project work without blocking local delivery."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_PROJECT_NUMBER = 7
STATUS_OPTIONS = frozenset({"Backlog", "Ready", "In progress", "In review", "Blocked", "Done"})
TYPE_LABELS = {
    "type:epic": "Epic",
    "type:story": "Story",
    "type:task": "Task",
    "type:spike": "Spike",
}
PRIORITY_LABELS = {
    "priority:p0": "P0 - now",
    "priority:p1": "P1 - next",
    "priority:p2": "P2 - later",
    "priority:p3": "P3 - someday",
}


class BoardUnavailableError(RuntimeError):
    """Report a remote GitHub failure that must not block local work by default."""


class IssueContractError(ValueError):
    """Report a reachable issue that does not satisfy the required local contract."""


@dataclass(frozen=True)
class IssueRecord:
    """Canonical issue lifecycle data used to derive project fields."""

    number: int
    state: str
    labels: frozenset[str]
    url: str
    body: str = ""


@dataclass(frozen=True)
class ProjectItem:
    """Mutable project projection for one repository issue."""

    item_id: str
    number: int
    repository: str
    status: str | None
    work_type: str | None
    priority: str | None


def desired_status(issue: IssueRecord, current: str | None) -> str:
    """Derive lifecycle-owned statuses while preserving explicit active queue states."""
    if issue.state.upper() == "CLOSED":
        return "Done"
    if "completed" in issue.labels:
        return "In review"
    if "blocked" in issue.labels:
        return "Blocked"
    if current in {"Ready", "In progress"}:
        return current
    return "Backlog"


def desired_work_type(labels: frozenset[str]) -> str | None:
    """Map canonical type labels to the project Work type field."""
    if "bug" in labels:
        return "Bug"
    matches = [value for label, value in TYPE_LABELS.items() if label in labels]
    return matches[0] if len(matches) == 1 else None


def desired_priority(labels: frozenset[str]) -> str | None:
    """Map one canonical priority label to the project Priority field."""
    matches = [value for label, value in PRIORITY_LABELS.items() if label in labels]
    return matches[0] if len(matches) == 1 else None


def has_exit_contract(body: str) -> bool:
    """Return whether an issue body has a named heading and a checkable criterion."""
    heading = re.search(r"^#{2,3}\s+(Exit criteria|Acceptance criteria)\s*$", body, re.I | re.M)
    checkbox = re.search(r"^\s*-\s+\[[ xX]\]\s+\S", body, re.M)
    return heading is not None and checkbox is not None


class GitHubClient:
    """Run bounded GitHub CLI calls and expose only board-specific operations."""

    def __init__(self, *, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds

    def run(self, arguments: Sequence[str]) -> str:
        """Run one bounded gh call and raise a degradable remote error on failure."""
        try:
            completed = subprocess.run(  # noqa: S603 - fixed gh executable and validated arguments
                ["gh", *arguments],
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BoardUnavailableError(str(error)) from error
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "unknown gh failure"
            raise BoardUnavailableError(detail)
        return completed.stdout

    def json(self, arguments: Sequence[str]) -> Any:
        """Run one gh call and decode its JSON response."""
        try:
            return json.loads(self.run(arguments))
        except json.JSONDecodeError as error:
            raise BoardUnavailableError(f"invalid JSON from gh: {error}") from error


def _labels(raw: object) -> frozenset[str]:
    values = raw if isinstance(raw, list) else []
    names: set[str] = set()
    for value in values:
        if isinstance(value, str):
            names.add(value)
        elif isinstance(value, dict) and isinstance(value.get("name"), str):
            names.add(value["name"])
    return frozenset(names)


def _issue(raw: dict[str, Any]) -> IssueRecord:
    return IssueRecord(
        number=int(raw["number"]),
        state=str(raw["state"]),
        labels=_labels(raw.get("labels")),
        url=str(raw["url"]),
        body=str(raw.get("body") or ""),
    )


def _project_item(raw: dict[str, Any]) -> ProjectItem | None:
    content = raw.get("content")
    if not isinstance(content, dict) or not isinstance(content.get("number"), int):
        return None
    return ProjectItem(
        item_id=str(raw["id"]),
        number=int(content["number"]),
        repository=str(raw.get("repository") or ""),
        status=str(raw["status"]) if raw.get("status") is not None else None,
        work_type=str(raw["work type"]) if raw.get("work type") is not None else None,
        priority=str(raw["priority"]) if raw.get("priority") is not None else None,
    )


def _repository(client: GitHubClient, configured: str | None) -> str:
    if configured:
        return configured
    raw = client.json(["repo", "view", "--json", "nameWithOwner"])
    name = raw.get("nameWithOwner") if isinstance(raw, dict) else None
    if not isinstance(name, str):
        raise BoardUnavailableError("gh repo view did not return nameWithOwner")
    return name


def _issue_record(client: GitHubClient, repository: str, number: int) -> IssueRecord:
    raw = client.json(
        [
            "issue",
            "view",
            str(number),
            "--repo",
            repository,
            "--json",
            "number,state,labels,url,body",
        ]
    )
    if not isinstance(raw, dict):
        raise BoardUnavailableError("gh issue view did not return an issue object")
    return _issue(raw)


def _issues(client: GitHubClient, repository: str) -> dict[int, IssueRecord]:
    raw = client.json(
        [
            "issue",
            "list",
            "--repo",
            repository,
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            "number,state,labels,url,body",
        ]
    )
    if not isinstance(raw, list):
        raise BoardUnavailableError("gh issue list did not return an array")
    records = (_issue(value) for value in raw if isinstance(value, dict))
    return {record.number: record for record in records}


def _project_items(
    client: GitHubClient,
    *,
    owner: str,
    project_number: int,
) -> dict[int, ProjectItem]:
    raw = client.json(
        [
            "project",
            "item-list",
            str(project_number),
            "--owner",
            owner,
            "--limit",
            "1000",
            "--format",
            "json",
        ]
    )
    values = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(values, list):
        raise BoardUnavailableError("gh project item-list did not return items")
    records = (_project_item(value) for value in values if isinstance(value, dict))
    return {record.number: record for record in records if record is not None}


def _project_metadata(
    client: GitHubClient,
    *,
    owner: str,
    project_number: int,
) -> tuple[str, dict[str, tuple[str, dict[str, str]]]]:
    project = client.json(
        ["project", "view", str(project_number), "--owner", owner, "--format", "json"]
    )
    fields = client.json(
        ["project", "field-list", str(project_number), "--owner", owner, "--format", "json"]
    )
    project_id = project.get("id") if isinstance(project, dict) else None
    values = fields.get("fields") if isinstance(fields, dict) else None
    if not isinstance(project_id, str) or not isinstance(values, list):
        raise BoardUnavailableError("project metadata is incomplete")
    metadata: dict[str, tuple[str, dict[str, str]]] = {}
    for field in values:
        field_id = field.get("id") if isinstance(field, dict) else None
        if not isinstance(field, dict) or not isinstance(field_id, str):
            continue
        options = field.get("options")
        option_values = options if isinstance(options, list) else []
        option_ids = {
            str(option["name"]): str(option["id"])
            for option in option_values
            if isinstance(option, dict)
            if option.get("name") is not None and option.get("id") is not None
        }
        metadata[str(field.get("name"))] = (field_id, option_ids)
    return project_id, metadata


def _add_item(
    client: GitHubClient,
    *,
    owner: str,
    project_number: int,
    issue: IssueRecord,
) -> str:
    raw = client.json(
        [
            "project",
            "item-add",
            str(project_number),
            "--owner",
            owner,
            "--url",
            issue.url,
            "--format",
            "json",
        ]
    )
    item_id = raw.get("id") if isinstance(raw, dict) else None
    if not isinstance(item_id, str):
        raise BoardUnavailableError("gh project item-add did not return an item id")
    return item_id


def _set_field(
    client: GitHubClient,
    *,
    project_id: str,
    item_id: str,
    metadata: dict[str, tuple[str, dict[str, str]]],
    field_name: str,
    option_name: str,
) -> None:
    field = metadata.get(field_name)
    if field is None or option_name not in field[1]:
        raise BoardUnavailableError(f"missing project option {field_name}={option_name}")
    client.run(
        [
            "project",
            "item-edit",
            "--id",
            item_id,
            "--project-id",
            project_id,
            "--field-id",
            field[0],
            "--single-select-option-id",
            field[1][option_name],
        ]
    )


def _apply_projection(
    client: GitHubClient,
    *,
    issue: IssueRecord,
    item: ProjectItem,
    project_id: str,
    metadata: dict[str, tuple[str, dict[str, str]]],
    status: str,
) -> int:
    changes = 0
    desired = {
        "Status": status,
        "Work type": desired_work_type(issue.labels),
        "Priority": desired_priority(issue.labels),
    }
    current = {
        "Status": item.status,
        "Work type": item.work_type,
        "Priority": item.priority,
    }
    for field_name, option_name in desired.items():
        if option_name is None or current[field_name] == option_name:
            continue
        _set_field(
            client,
            project_id=project_id,
            item_id=item.item_id,
            metadata=metadata,
            field_name=field_name,
            option_name=option_name,
        )
        changes += 1
    return changes


def start(
    client: GitHubClient,
    *,
    repository: str,
    owner: str,
    project_number: int,
    issue_number: int,
) -> int:
    """Claim an issue and project it into In progress without requiring planning fields."""
    issue = _issue_record(client, repository, issue_number)
    if not has_exit_contract(issue.body):
        raise IssueContractError(
            f"issue #{issue.number} needs an ## Exit criteria or ## Acceptance criteria checklist"
        )
    client.run(["issue", "edit", str(issue.number), "--repo", repository, "--add-assignee", "@me"])
    items = _project_items(client, owner=owner, project_number=project_number)
    item = items.get(issue.number)
    if item is None:
        item = ProjectItem(
            item_id=_add_item(
                client,
                owner=owner,
                project_number=project_number,
                issue=issue,
            ),
            number=issue.number,
            repository=repository,
            status=None,
            work_type=None,
            priority=None,
        )
    project_id, metadata = _project_metadata(
        client,
        owner=owner,
        project_number=project_number,
    )
    changes = _apply_projection(
        client,
        issue=issue,
        item=item,
        project_id=project_id,
        metadata=metadata,
        status="In progress",
    )
    print(f"project-board: started issue=#{issue.number} field_changes={changes}")
    return 0


def sync(
    client: GitHubClient,
    *,
    repository: str,
    owner: str,
    project_number: int,
    apply: bool,
) -> int:
    """Preview or apply issue-owned lifecycle fields across the project."""
    issues = _issues(client, repository)
    items = _project_items(client, owner=owner, project_number=project_number)
    project_id, metadata = _project_metadata(
        client,
        owner=owner,
        project_number=project_number,
    )
    proposed = 0
    applied = 0
    for number, issue in sorted(issues.items()):
        item = items.get(number)
        if item is None:
            proposed += 1
            print(f"add issue=#{number}")
            if not apply:
                continue
            item = ProjectItem(
                item_id=_add_item(
                    client,
                    owner=owner,
                    project_number=project_number,
                    issue=issue,
                ),
                number=number,
                repository=repository,
                status=None,
                work_type=None,
                priority=None,
            )
            applied += 1
        desired = {
            "Status": desired_status(issue, item.status),
            "Work type": desired_work_type(issue.labels),
            "Priority": desired_priority(issue.labels),
        }
        current = {
            "Status": item.status,
            "Work type": item.work_type,
            "Priority": item.priority,
        }
        differences = [
            f"{field_name}={option_name}"
            for field_name, option_name in desired.items()
            if option_name is not None and current[field_name] != option_name
        ]
        if not differences:
            continue
        proposed += len(differences)
        print(f"update issue=#{number} " + " ".join(differences))
        if apply:
            applied += _apply_projection(
                client,
                issue=issue,
                item=item,
                project_id=project_id,
                metadata=metadata,
                status=desired["Status"] or "Backlog",
            )
    print(f"project-board: sync proposed={proposed} applied={applied} apply={str(apply).lower()}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        help="Repository in OWNER/NAME form; defaults to the current repo",
    )
    parser.add_argument("--owner", help="Project owner; defaults to the repository owner")
    parser.add_argument(
        "--project-number",
        type=int,
        default=int(os.environ.get("FDAI_GITHUB_PROJECT_NUMBER", DEFAULT_PROJECT_NUMBER)),
    )
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return nonzero when GitHub or the Project API is unavailable",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("issue", type=int)
    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--apply", action="store_true")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    if arguments.project_number <= 0 or arguments.timeout_seconds <= 0:
        print("project-board: project number and timeout must be positive", file=sys.stderr)
        return 2
    client = GitHubClient(timeout_seconds=arguments.timeout_seconds)
    try:
        repository = _repository(client, arguments.repo)
        owner = arguments.owner or repository.partition("/")[0]
        if arguments.command == "start":
            return start(
                client,
                repository=repository,
                owner=owner,
                project_number=arguments.project_number,
                issue_number=arguments.issue,
            )
        return sync(
            client,
            repository=repository,
            owner=owner,
            project_number=arguments.project_number,
            apply=arguments.apply,
        )
    except IssueContractError as error:
        print(f"project-board: ERROR: {error}", file=sys.stderr)
        return 2
    except BoardUnavailableError as error:
        level = "ERROR" if arguments.strict else "WARN"
        print(f"project-board: {level}: sync deferred: {error}", file=sys.stderr)
        return 1 if arguments.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
