"""Contracts for non-blocking GitHub Project synchronization."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "automation" / "project-board.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("project_board", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(SCRIPT.parent))
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def board() -> ModuleType:
    return _load_module()


def _issue(
    board: ModuleType,
    *,
    state: str = "OPEN",
    labels: frozenset[str] = frozenset(),
) -> object:
    return board.IssueRecord(
        number=95,
        state=state,
        labels=labels,
        url="https://example.com/issues/95",
    )


@pytest.mark.parametrize(
    ("state", "labels", "current", "expected"),
    [
        ("CLOSED", frozenset({"blocked"}), "Blocked", "Done"),
        ("OPEN", frozenset({"completed"}), "In progress", "In review"),
        ("OPEN", frozenset({"blocked"}), "Ready", "Blocked"),
        ("OPEN", frozenset(), "Done", "Backlog"),
        ("OPEN", frozenset(), "In progress", "In progress"),
        ("OPEN", frozenset(), "Ready", "Ready"),
        ("OPEN", frozenset(), None, "Backlog"),
    ],
)
def test_desired_status_follows_issue_lifecycle_then_preserves_active_work(
    board: ModuleType,
    state: str,
    labels: frozenset[str],
    current: str | None,
    expected: str,
) -> None:
    assert board.desired_status(_issue(board, state=state, labels=labels), current) == expected


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (frozenset({"type:epic"}), "Epic"),
        (frozenset({"type:story"}), "Story"),
        (frozenset({"type:task"}), "Task"),
        (frozenset({"type:spike"}), "Spike"),
        (frozenset({"bug", "type:task"}), "Bug"),
        (frozenset({"type:story", "type:task"}), None),
        (frozenset(), None),
    ],
)
def test_desired_work_type_requires_one_canonical_type(
    board: ModuleType,
    labels: frozenset[str],
    expected: str | None,
) -> None:
    assert board.desired_work_type(labels) == expected


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (frozenset({"priority:p0"}), "P0 - now"),
        (frozenset({"priority:p1"}), "P1 - next"),
        (frozenset({"priority:p2"}), "P2 - later"),
        (frozenset({"priority:p3"}), "P3 - someday"),
        (frozenset({"priority:p0", "priority:p1"}), None),
        (frozenset(), None),
    ],
)
def test_desired_priority_requires_one_canonical_priority(
    board: ModuleType,
    labels: frozenset[str],
    expected: str | None,
) -> None:
    assert board.desired_priority(labels) == expected


def test_exit_contract_requires_heading_and_checkbox(board: ModuleType) -> None:
    assert board.has_exit_contract("## Exit criteria\n\n- [ ] Focused checks pass.\n")
    assert board.has_exit_contract("### Acceptance criteria\n\n- [x] Behavior is proven.\n")
    assert not board.has_exit_contract("## Exit criteria\n\nFocused checks pass.\n")
    assert not board.has_exit_contract("- [ ] Focused checks pass.\n")


def test_project_items_ignore_same_number_from_another_repository(board: ModuleType) -> None:
    class Client:
        @staticmethod
        def json(_arguments: object) -> dict[str, object]:
            return {
                "items": [
                    {
                        "id": "other-item",
                        "repository": "https://github.com/example/other",
                        "status": "Done",
                        "content": {"number": 95},
                    },
                    {
                        "id": "fdai-item",
                        "repository": "https://github.com/dotnetpower/fdai",
                        "status": "In progress",
                        "content": {"number": 95, "repository": "dotnetpower/fdai"},
                    },
                ]
            }

    items = board.project_items(
        Client(),
        repository="dotnetpower/fdai",
        owner="dotnetpower",
        project_number=7,
    )

    assert items[95].item_id == "fdai-item"
    assert items[95].status == "In progress"


@pytest.mark.parametrize(("strict", "expected"), [(False, 0), (True, 1)])
def test_remote_failure_is_nonblocking_unless_strict(
    board: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    strict: bool,
    expected: int,
) -> None:
    def unavailable(_client: object, _configured: object) -> str:
        raise board.BoardUnavailableError("offline")

    arguments = [str(SCRIPT)]
    if strict:
        arguments.append("--strict")
    arguments.extend(["start", "95"])
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(board, "repository_name", unavailable)

    assert board.main() == expected
    level = "ERROR" if strict else "WARN"
    assert f"project-board: {level}: sync deferred: offline" in capsys.readouterr().err
