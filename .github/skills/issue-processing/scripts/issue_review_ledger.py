#!/usr/bin/env python3
"""Select and record bounded GitHub issue-review batches in private local state."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_BATCH_SIZE = 10
MAX_BATCH_SIZE = 10
STATE_DIRECTORY = "fdai-issue-processing"
LEDGER_FILENAME = "reviews.jsonl"
VERDICTS = ("complete", "partial", "obsolete", "blocked")
ACTIONS = ("closed", "closed-not-planned", "kept-open", "review-needed", "deferred")


class LedgerError(RuntimeError):
    """Report an invalid ledger or unavailable local/GitHub boundary."""


@dataclass(frozen=True)
class Issue:
    """Represent the issue fields that control batch selection and review identity."""

    number: int
    title: str
    created_at: str
    updated_at: str
    state: str
    labels: tuple[str, ...]
    url: str
    body: str


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
        raise LedgerError(str(error)) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise LedgerError(detail)
    return result.stdout


def repository_name(configured: str | None) -> str:
    """Return an explicit repository or the current GitHub repository name."""
    if configured:
        return configured
    value = _run(("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"))
    repository = value.strip()
    if "/" not in repository:
        raise LedgerError("unable to resolve the current GitHub repository")
    return repository


def default_ledger_path() -> Path:
    """Return a private state path shared by all worktrees of this repository."""
    raw = Path(_run(("git", "rev-parse", "--path-format=absolute", "--git-common-dir")).strip())
    return raw / STATE_DIRECTORY / LEDGER_FILENAME


def _label_names(raw: object) -> tuple[str, ...]:
    values = raw if isinstance(raw, list) else []
    names = {
        str(value.get("name"))
        for value in values
        if isinstance(value, dict) and isinstance(value.get("name"), str)
    }
    return tuple(sorted(names))


def issue_from_json(raw: Mapping[str, Any]) -> Issue:
    """Normalize one GitHub CLI issue payload."""
    return Issue(
        number=int(raw["number"]),
        title=str(raw["title"]),
        created_at=str(raw["createdAt"]),
        updated_at=str(raw["updatedAt"]),
        state=str(raw["state"]),
        labels=_label_names(raw.get("labels")),
        url=str(raw["url"]),
        body=str(raw.get("body") or ""),
    )


def issue_fingerprint(issue: Issue) -> str:
    """Hash material issue fields while ignoring comments and volatile timestamps."""
    payload = {
        "body": issue.body,
        "labels": issue.labels,
        "title": issue.title,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def list_open_issues(repository: str) -> list[Issue]:
    """Fetch open issues and return them in stable oldest-first order."""
    output = _run(
        (
            "gh",
            "issue",
            "list",
            "--repo",
            repository,
            "--state",
            "open",
            "--search",
            "is:issue sort:created-asc",
            "--limit",
            "1000",
            "--json",
            "number,title,createdAt,updatedAt,state,labels,url,body",
        )
    )
    try:
        raw = json.loads(output)
    except json.JSONDecodeError as error:
        raise LedgerError(f"invalid JSON from gh: {error}") from error
    if not isinstance(raw, list):
        raise LedgerError("gh issue list did not return a JSON array")
    issues = [issue_from_json(item) for item in raw if isinstance(item, dict)]
    return sorted(issues, key=lambda issue: (issue.created_at, issue.number))


def get_issue(repository: str, number: int) -> Issue:
    """Fetch one issue after lifecycle actions so the ledger records final state."""
    output = _run(
        (
            "gh",
            "issue",
            "view",
            str(number),
            "--repo",
            repository,
            "--json",
            "number,title,createdAt,updatedAt,state,labels,url,body",
        )
    )
    try:
        raw = json.loads(output)
    except json.JSONDecodeError as error:
        raise LedgerError(f"invalid JSON from gh: {error}") from error
    if not isinstance(raw, dict):
        raise LedgerError("gh issue view did not return a JSON object")
    return issue_from_json(raw)


def read_events(path: Path) -> list[dict[str, Any]]:
    """Read every append-only event and reject malformed state."""
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise LedgerError(f"invalid ledger JSON at line {line_number}: {error}") from error
        if not isinstance(event, dict) or not isinstance(event.get("issue_number"), int):
            raise LedgerError(f"invalid ledger event at line {line_number}")
        if event.get("event") not in {"reviewed", "requeued"}:
            raise LedgerError(f"unknown ledger event at line {line_number}")
        events.append(event)
    return events


def latest_events(events: Iterable[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    """Return the latest append-only event for each issue."""
    latest: dict[int, Mapping[str, Any]] = {}
    for event in events:
        latest[int(event["issue_number"])] = event
    return latest


def select_next(
    issues: Iterable[Issue], latest: Mapping[int, Mapping[str, Any]], *, limit: int
) -> list[Issue]:
    """Select oldest issues without a current terminal review record."""
    if not 1 <= limit <= MAX_BATCH_SIZE:
        raise LedgerError(f"batch limit must be between 1 and {MAX_BATCH_SIZE}")
    selected: list[Issue] = []
    for issue in sorted(issues, key=lambda value: (value.created_at, value.number)):
        event = latest.get(issue.number)
        current_review = (
            event is not None
            and event.get("event") == "reviewed"
            and event.get("issue_fingerprint") == issue_fingerprint(issue)
        )
        if current_review:
            continue
        selected.append(issue)
        if len(selected) == limit:
            break
    return selected


def append_event(path: Path, event: Mapping[str, Any]) -> None:
    """Append one private event under an exclusive file lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(json.dumps(dict(event), ensure_ascii=True, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    os.chmod(path, 0o600)


def _head_sha() -> str:
    return _run(("git", "rev-parse", "HEAD")).strip()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _issue_output(issue: Issue) -> dict[str, Any]:
    result = asdict(issue)
    result["fingerprint"] = issue_fingerprint(issue)
    result["labels"] = list(issue.labels)
    return result


def _print_table(issues: Sequence[Issue]) -> None:
    print("number\tcreated_at\ttitle")
    for issue in issues:
        print(f"{issue.number}\t{issue.created_at}\t{issue.title}")


def _record(args: argparse.Namespace, ledger: Path, repository: str) -> None:
    issue = get_issue(repository, args.number)
    append_event(
        ledger,
        {
            "schema_version": 1,
            "event": "reviewed",
            "issue_number": issue.number,
            "issue_title": issue.title,
            "issue_url": issue.url,
            "issue_state": issue.state,
            "issue_updated_at": issue.updated_at,
            "issue_fingerprint": issue_fingerprint(issue),
            "reviewed_at": _now(),
            "reviewed_head": _head_sha(),
            "verdict": args.verdict,
            "action": args.action,
            "evidence": args.evidence,
        },
    )
    print(f"issue-review-ledger: recorded issue=#{issue.number} verdict={args.verdict}")


def _requeue(args: argparse.Namespace, ledger: Path) -> None:
    append_event(
        ledger,
        {
            "schema_version": 1,
            "event": "requeued",
            "issue_number": args.number,
            "requeued_at": _now(),
            "requeued_head": _head_sha(),
            "reason": args.reason,
        },
    )
    print(f"issue-review-ledger: requeued issue=#{args.number}")


def _status(issues: Sequence[Issue], events: Sequence[Mapping[str, Any]]) -> None:
    latest = latest_events(events)
    current = sum(
        1
        for issue in issues
        if (event := latest.get(issue.number)) is not None
        and event.get("event") == "reviewed"
        and event.get("issue_fingerprint") == issue_fingerprint(issue)
    )
    stale = sum(
        1
        for issue in issues
        if (event := latest.get(issue.number)) is not None
        and event.get("event") == "reviewed"
        and event.get("issue_fingerprint") != issue_fingerprint(issue)
    )
    reviewed_total = sum(1 for event in latest.values() if event.get("event") == "reviewed")
    print(
        "issue-review-ledger: "
        f"open={len(issues)} current_open_reviews={current} "
        f"changed_since_review={stale} reviewed_total={reviewed_total} "
        f"unreviewed_open={len(issues) - current}"
    )


def parser() -> argparse.ArgumentParser:
    """Build the command-line contract for issue selection and review persistence."""
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--repo", help="GitHub OWNER/REPO; defaults to the current repository")
    value.add_argument("--ledger", type=Path, help="Override the private local ledger path")
    commands = value.add_subparsers(dest="command", required=True)

    next_parser = commands.add_parser("next", help="Select the oldest unreviewed open issues")
    next_parser.add_argument("--limit", type=int, default=DEFAULT_BATCH_SIZE)
    next_parser.add_argument("--json", action="store_true")

    commands.add_parser("status", help="Report review-ledger coverage")

    record_parser = commands.add_parser("record", help="Record a confirmed terminal review")
    record_parser.add_argument("number", type=int)
    record_parser.add_argument("--verdict", required=True, choices=VERDICTS)
    record_parser.add_argument("--action", required=True, choices=ACTIONS)
    record_parser.add_argument("--evidence", required=True)

    requeue_parser = commands.add_parser("requeue", help="Make a reviewed issue eligible again")
    requeue_parser.add_argument("number", type=int)
    requeue_parser.add_argument("--reason", required=True)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    """Run one bounded ledger operation and return a shell-friendly status."""
    args = parser().parse_args(argv)
    try:
        ledger = args.ledger or default_ledger_path()
        if args.command == "requeue":
            _requeue(args, ledger)
            return 0
        repository = repository_name(args.repo)
        if args.command == "record":
            _record(args, ledger, repository)
            return 0
        issues = list_open_issues(repository)
        events = read_events(ledger)
        if args.command == "status":
            _status(issues, events)
            return 0
        selected = select_next(issues, latest_events(events), limit=args.limit)
        if args.json:
            print(json.dumps([_issue_output(issue) for issue in selected], indent=2))
        else:
            _print_table(selected)
        return 0
    except LedgerError as error:
        print(f"issue-review-ledger: ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
