#!/usr/bin/env python3
"""Start and reconcile FDAI GitHub Project work without blocking local delivery."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.project_board_support import (  # noqa: E402
    DEFAULT_PROJECT_NUMBER,
    BoardUnavailableError,
    GitHubClient,
    IssueContractError,
    IssueRecord,
    ProjectItem,
    add_item,
    desired_priority,
    desired_status,
    desired_work_type,
    has_exit_contract,
    issue_record,
    issue_records,
    project_items,
    project_metadata,
    repository_name,
    set_field,
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
        set_field(
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
    issue = issue_record(client, repository, issue_number)
    if not has_exit_contract(issue.body):
        raise IssueContractError(
            f"issue #{issue.number} needs an ## Exit criteria or ## Acceptance criteria checklist"
        )
    client.run(["issue", "edit", str(issue.number), "--repo", repository, "--add-assignee", "@me"])
    items = project_items(
        client,
        repository=repository,
        owner=owner,
        project_number=project_number,
    )
    item = items.get(issue.number)
    if item is None:
        item = ProjectItem(
            item_id=add_item(
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
    project_id, metadata = project_metadata(
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
    issues = issue_records(client, repository)
    items = project_items(
        client,
        repository=repository,
        owner=owner,
        project_number=project_number,
    )
    project_id, metadata = project_metadata(
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
                item_id=add_item(
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
        repository = repository_name(client, arguments.repo)
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
