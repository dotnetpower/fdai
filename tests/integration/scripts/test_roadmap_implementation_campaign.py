from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

AUTOMATION = Path(__file__).resolve().parents[3] / "scripts" / "automation"


def _load() -> ModuleType:
    sys.path.insert(0, str(AUTOMATION))
    path = AUTOMATION / "roadmap_implementation_campaign.py"
    spec = importlib.util.spec_from_file_location("fdai_roadmap_implementation_campaign", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_choose_folder_requires_a_complete_batch() -> None:
    module = _load()
    grouped = {
        "interfaces": [f"docs/roadmap/interfaces/doc-{index}.md" for index in range(10)],
        "operations": [f"docs/roadmap/operations/doc-{index}.md" for index in range(9)],
    }

    selected = module.choose_folder(grouped, chooser=lambda folders: folders[0])

    assert selected == ("interfaces", grouped["interfaces"])
    assert module.choose_folder({"operations": grouped["operations"]}) is None


def test_campaign_allows_two_active_sessions_and_holds_three() -> None:
    module = _load()

    assert module._within_session_capacity(2, 2)
    assert not module._within_session_capacity(3, 2)


@pytest.mark.parametrize(
    ("ahead", "behind", "expected"),
    [
        (0, 0, "current"),
        (0, 2, "behind"),
        (2, 0, "ahead"),
        (1, 1, "diverged"),
    ],
)
def test_campaign_relation_fails_closed_on_divergence(
    ahead: int,
    behind: int,
    expected: str,
) -> None:
    module = _load()

    assert module._campaign_relation(ahead=ahead, behind=behind) == expected


def test_campaign_prompt_requires_exact_batch_and_hardening_floor() -> None:
    module = _load()
    candidates = [f"docs/roadmap/interfaces/doc-{index}.md" for index in range(12)]
    issue = module.project_board.IssueRecord(
        number=123,
        state="OPEN",
        labels=frozenset({"type:task"}),
        url="https://example.com/issues/123",
        body="## Exit criteria\n- [ ] Complete the interface work.\n",
    )

    prompt = module.campaign_prompt("interfaces", candidates, issue=issue)

    assert "exactly 10 canonical English documents" in prompt
    assert "at least 10 explicit" in prompt
    assert "remaining verified severity is Low or none" in prompt
    assert "issue #123" in prompt
    assert "Complete the interface work" in prompt
    assert "Never run repository-wide validation" in prompt


def test_choose_issue_requires_registered_executable_unfinished_work() -> None:
    module = _load()
    issue_type = module.project_board.IssueRecord
    item_type = module.project_board.ProjectItem
    issues = {
        10: issue_type(
            number=10,
            state="OPEN",
            labels=frozenset(),
            url="https://example.com/issues/10",
            body="## Exit criteria\n- [ ] Resume active work.\n",
        ),
        11: issue_type(
            number=11,
            state="OPEN",
            labels=frozenset(),
            url="https://example.com/issues/11",
            body="## Exit criteria\n- [ ] Start ready work.\n",
        ),
        12: issue_type(
            number=12,
            state="OPEN",
            labels=frozenset({"blocked"}),
            url="https://example.com/issues/12",
            body="## Exit criteria\n- [ ] Blocked work.\n",
        ),
        13: issue_type(
            number=13,
            state="OPEN",
            labels=frozenset(),
            url="https://example.com/issues/13",
            body="## Exit criteria\n- [x] Already complete.\n",
        ),
    }
    items = {
        10: item_type("item-10", 10, "dotnetpower/fdai", "In progress", "Task", "P2 - later"),
        11: item_type("item-11", 11, "dotnetpower/fdai", "Ready", "Task", "P0 - now"),
        12: item_type("item-12", 12, "dotnetpower/fdai", "Ready", "Task", "P0 - now"),
        13: item_type("item-13", 13, "dotnetpower/fdai", "Ready", "Task", "P0 - now"),
    }

    assert module.choose_issue(issues, items) == issues[10]
    assert module.choose_issue({11: issues[11]}, {}) is None


def test_validate_completed_result_enforces_batch_rounds_and_severity(tmp_path: Path) -> None:
    module = _load()
    candidates = []
    evidence = tmp_path / "tests/test_example.py"
    evidence.parent.mkdir()
    evidence.write_text("def test_example(): pass\n", encoding="utf-8")
    for index in range(10):
        relative = f"docs/roadmap/interfaces/doc-{index}.md"
        candidates.append(relative)
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Example\n", encoding="utf-8")
    payload = {
        "outcome": "completed",
        "issue": 123,
        "folder": "interfaces",
        "documents": candidates,
        "hardening_rounds": 10,
        "remaining_max_severity": "low",
        "summary": "Implemented and hardened ten bounded items.",
        "evidence_paths": ["tests/test_example.py"],
        "tests": ["pytest tests/test_example.py: passed"],
    }

    result = module.validate_result(
        payload,
        repo_root=tmp_path,
        issue_number=123,
        folder="interfaces",
        candidates=candidates,
    )

    assert result["documents"] == candidates
    with pytest.raises(RuntimeError, match="at least ten hardening rounds"):
        module.validate_result(
            {**payload, "hardening_rounds": 9},
            repo_root=tmp_path,
            issue_number=123,
            folder="interfaces",
            candidates=candidates,
        )
    with pytest.raises(RuntimeError, match="above Low"):
        module.validate_result(
            {**payload, "remaining_max_severity": "medium"},
            repo_root=tmp_path,
            issue_number=123,
            folder="interfaces",
            candidates=candidates,
        )
    with pytest.raises(RuntimeError, match="selected issue"):
        module.validate_result(
            {**payload, "issue": 456},
            repo_root=tmp_path,
            issue_number=123,
            folder="interfaces",
            candidates=candidates,
        )


def test_require_document_updates_checks_both_languages() -> None:
    module = _load()
    documents = [f"docs/roadmap/interfaces/doc-{index}.md" for index in range(10)]
    changed = [
        path
        for document in documents
        for path in (document, document.removesuffix(".md") + "-ko.md")
    ]

    module._require_document_updates({"documents": documents}, changed)
    with pytest.raises(RuntimeError, match="English/Korean"):
        module._require_document_updates({"documents": documents}, changed[:-1])


def test_installer_discovers_issues_and_repeats_persistently(tmp_path: Path) -> None:
    path = AUTOMATION / "install_roadmap_implementation_campaign.py"
    spec = importlib.util.spec_from_file_location("fdai_roadmap_campaign_installer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    installer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = installer
    spec.loader.exec_module(installer)

    service, timer = installer._unit_text(tmp_path.resolve())

    assert "roadmap_implementation_campaign.py" in service
    assert "--issue" not in service
    assert "--max-active-sessions 2" in service
    assert "OnUnitInactiveSec=5min" in timer
    assert "Persistent=true" in timer
    assert "TimeoutStartSec=5h" in service
