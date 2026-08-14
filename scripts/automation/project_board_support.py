"""Shared lifecycle policy and bounded GitHub transport for project synchronization."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_PROJECT_NUMBER = 7
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


def issue_record_from_json(raw: dict[str, Any]) -> IssueRecord:
    """Normalize one gh issue response into canonical lifecycle data."""
    return IssueRecord(
        number=int(raw["number"]),
        state=str(raw["state"]),
        labels=_labels(raw.get("labels")),
        url=str(raw["url"]),
        body=str(raw.get("body") or ""),
    )


def project_item_from_json(raw: dict[str, Any]) -> ProjectItem | None:
    """Normalize one issue-backed project item and ignore draft content."""
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


def repository_name(client: GitHubClient, configured: str | None) -> str:
    """Resolve the configured or current OWNER/NAME repository identity."""
    if configured:
        return configured
    raw = client.json(["repo", "view", "--json", "nameWithOwner"])
    name = raw.get("nameWithOwner") if isinstance(raw, dict) else None
    if not isinstance(name, str):
        raise BoardUnavailableError("gh repo view did not return nameWithOwner")
    return name


def issue_record(client: GitHubClient, repository: str, number: int) -> IssueRecord:
    """Read one canonical issue record."""
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
    return issue_record_from_json(raw)


def issue_records(client: GitHubClient, repository: str) -> dict[int, IssueRecord]:
    """Read every issue needed for one repository reconciliation."""
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
    records = (issue_record_from_json(value) for value in raw if isinstance(value, dict))
    return {record.number: record for record in records}


def project_items(
    client: GitHubClient,
    *,
    repository: str,
    owner: str,
    project_number: int,
) -> dict[int, ProjectItem]:
    """Read issue-backed items from one GitHub Project."""
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
    records = (project_item_from_json(value) for value in values if isinstance(value, dict))
    return {
        record.number: record
        for record in records
        if record is not None and record.repository == repository
    }


def project_metadata(
    client: GitHubClient,
    *,
    owner: str,
    project_number: int,
) -> tuple[str, dict[str, tuple[str, dict[str, str]]]]:
    """Resolve stable project, field, and single-select option ids by name."""
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


def add_item(
    client: GitHubClient,
    *,
    owner: str,
    project_number: int,
    issue: IssueRecord,
) -> str:
    """Add one issue to the project and return its item id."""
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


def set_field(
    client: GitHubClient,
    *,
    project_id: str,
    item_id: str,
    metadata: dict[str, tuple[str, dict[str, str]]],
    field_name: str,
    option_name: str,
) -> None:
    """Set one validated single-select project field."""
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
