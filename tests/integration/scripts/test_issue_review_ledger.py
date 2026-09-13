"""Focused contracts for oldest-first issue review selection and local persistence."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[3]
    / ".github"
    / "skills"
    / "issue-processing"
    / "scripts"
    / "issue_review_ledger.py"
)
WORKER_LABEL_SCRIPT = SCRIPT.with_name("issue_worker_label.py")


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("issue_review_ledger", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ledger = _module()


def _worker_label_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("issue_worker_label", WORKER_LABEL_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _issue(number: int, *, body: str = "body") -> object:
    return ledger.Issue(
        number=number,
        title=f"Issue {number}",
        created_at=f"2026-01-{number:02d}T00:00:00Z",
        updated_at=f"2026-02-{number:02d}T00:00:00Z",
        state="OPEN",
        labels=("area:test", "type:task"),
        url=f"https://github.com/example/repository/issues/{number}",
        body=body,
    )


def test_select_next_skips_current_reviews_and_preserves_oldest_order() -> None:
    issues = [_issue(number) for number in range(1, 13)]
    latest = {
        1: {
            "event": "reviewed",
            "issue_number": 1,
            "issue_fingerprint": ledger.issue_fingerprint(issues[0]),
        },
        3: {"event": "requeued", "issue_number": 3},
    }

    selected = ledger.select_next(issues, latest, limit=10)

    assert [issue.number for issue in selected] == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]


def test_select_next_reselects_materially_changed_issue() -> None:
    reviewed = _issue(1, body="old body")
    changed = _issue(1, body="new body")
    latest = {
        1: {
            "event": "reviewed",
            "issue_number": 1,
            "issue_fingerprint": ledger.issue_fingerprint(reviewed),
        }
    }

    assert ledger.select_next([changed], latest, limit=10) == [changed]


def test_append_and_read_events_preserve_latest_state(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    ledger.append_event(path, {"event": "reviewed", "issue_number": 7})
    ledger.append_event(path, {"event": "requeued", "issue_number": 7})

    events = ledger.read_events(path)

    assert ledger.latest_events(events)[7]["event"] == "requeued"
    assert path.stat().st_mode & 0o777 == 0o600


def test_select_next_rejects_batch_larger_than_ten() -> None:
    with pytest.raises(ledger.LedgerError, match="between 1 and 10"):
        ledger.select_next([_issue(1)], {}, limit=11)


def test_worker_label_normalizes_hostname() -> None:
    worker_label = _worker_label_module()

    assert worker_label.label_for_hostname("Worker One.example") == "inprogress:worker-one.example"


def test_claim_is_idempotent_for_current_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    worker_label = _worker_label_module()
    commands: list[tuple[str, ...]] = []

    def run(arguments: tuple[str, ...], *, timeout: float = 30) -> str:
        commands.append(arguments)
        if arguments[1:3] == ("issue", "view"):
            return '{"labels":[{"name":"inprogress:worker-one"}]}'
        return ""

    monkeypatch.setattr(worker_label, "_run", run)

    worker_label.claim("example/repository", [17], hostname="worker-one")

    assert not any("--add-label" in command for command in commands)


def test_claim_creates_adds_and_verifies_worker_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_label = _worker_label_module()
    commands: list[tuple[str, ...]] = []
    claimed = False

    def run(arguments: tuple[str, ...], *, timeout: float = 30) -> str:
        nonlocal claimed
        commands.append(arguments)
        if arguments[1:3] == ("issue", "view"):
            labels = [{"name": "inprogress:worker-one"}] if claimed else []
            return json.dumps({"labels": labels})
        if arguments[1:3] == ("issue", "edit"):
            claimed = True
        return ""

    monkeypatch.setattr(worker_label, "_run", run)

    assert (
        worker_label.claim("example/repository", [17], hostname="worker-one")
        == "inprogress:worker-one"
    )
    assert any(command[1:3] == ("label", "create") for command in commands)
    assert any("--add-label" in command for command in commands)


def test_claim_rejects_foreign_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    worker_label = _worker_label_module()
    monkeypatch.setattr(
        worker_label,
        "_run",
        lambda *_args, **_kwargs: '{"labels":[{"name":"inprogress:other-host"}]}',
    )

    with pytest.raises(worker_label.WorkerLabelError, match="other-host"):
        worker_label.claim("example/repository", [17], hostname="worker-one")


def test_release_removes_only_current_worker_label(monkeypatch: pytest.MonkeyPatch) -> None:
    worker_label = _worker_label_module()
    commands: list[tuple[str, ...]] = []
    released = False

    def run(arguments: tuple[str, ...], *, timeout: float = 30) -> str:
        nonlocal released
        commands.append(arguments)
        if arguments[1:3] == ("issue", "view"):
            current_label = "" if released else '{"name":"inprogress:worker-one"},'
            return f'{{"labels":[{current_label}{{"name":"inprogress:other-host"}}]}}'
        if arguments[1:3] == ("issue", "edit"):
            released = True
        return ""

    monkeypatch.setattr(worker_label, "_run", run)

    worker_label.release("example/repository", [17], hostname="worker-one")

    edits = [command for command in commands if command[1:3] == ("issue", "edit")]
    assert edits == [
        (
            "gh",
            "issue",
            "edit",
            "17",
            "--repo",
            "example/repository",
            "--remove-label",
            "inprogress:worker-one",
        )
    ]


def test_release_attempts_every_issue_before_reporting_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_label = _worker_label_module()
    edits: list[int] = []

    def run(arguments: tuple[str, ...], *, timeout: float = 30) -> str:
        if arguments[1:3] == ("issue", "edit"):
            edits.append(int(arguments[3]))
            return ""
        if arguments[1:3] == ("issue", "view"):
            issue_number = int(arguments[3])
            claimed = issue_number == 17 or issue_number not in edits
            labels = [{"name": "inprogress:worker-one"}] if claimed else []
            return json.dumps({"labels": labels})
        return ""

    monkeypatch.setattr(worker_label, "_run", run)

    with pytest.raises(worker_label.WorkerLabelError, match="issue #17"):
        worker_label.release(
            "example/repository",
            [17, 18],
            hostname="worker-one",
        )

    assert edits == [17, 18]
