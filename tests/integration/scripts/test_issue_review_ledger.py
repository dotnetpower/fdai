"""Focused contracts for oldest-first issue review selection and local persistence."""

from __future__ import annotations

import importlib.util
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


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("issue_review_ledger", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ledger = _module()


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
