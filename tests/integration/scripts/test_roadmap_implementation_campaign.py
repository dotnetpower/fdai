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
        "interfaces": [
            f"docs/roadmap/interfaces/doc-{index}.md" for index in range(module.BATCH_SIZE)
        ],
        "operations": [
            f"docs/roadmap/operations/doc-{index}.md" for index in range(module.BATCH_SIZE - 1)
        ],
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
    candidates = [
        f"docs/roadmap/interfaces/doc-{index}.md" for index in range(module.BATCH_SIZE + 2)
    ]
    issue = module.project_board.IssueRecord(
        number=123,
        state="OPEN",
        labels=frozenset({"type:task"}),
        url="https://example.com/issues/123",
        body="## Exit criteria\n- [ ] Complete the interface work.\n",
    )

    prompt = module.campaign_prompt("interfaces", candidates, issue=issue)

    # The prompt must state the same numbers the validator enforces; a copied literal in either
    # place drifts silently and the agent is judged against a contract it was never given.
    assert f"exactly {module.BATCH_SIZE} canonical English documents" in prompt
    assert f"at least {module.MIN_HARDENING_ROUNDS} explicit" in prompt
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
    for index in range(module.BATCH_SIZE):
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
        "hardening_rounds": module.MIN_HARDENING_ROUNDS,
        "remaining_max_severity": "low",
        "summary": "Implemented and hardened the bounded items.",
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
    with pytest.raises(RuntimeError, match="hardening rounds"):
        module.validate_result(
            {**payload, "hardening_rounds": module.MIN_HARDENING_ROUNDS - 1},
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
    assert "TimeoutStartSec=2h" in service


def test_refusal_memo_expires_and_fails_open(tmp_path: Path) -> None:
    module = _load()

    module.record_refusal(tmp_path, 63, "deployment", now=1_000.0)
    module.record_refusal(tmp_path, 63, "architecture", now=1_000.0)

    assert module.refused_folders(tmp_path, 63, now=1_000.0) == frozenset(
        {"deployment", "architecture"}
    )
    # Another issue must not inherit this issue's refusals.
    assert module.refused_folders(tmp_path, 64, now=1_000.0) == frozenset()
    # A refusal is a hint with an expiry, not a permanent exclusion.
    assert (
        module.refused_folders(tmp_path, 63, now=1_000.0 + module.REFUSAL_TTL_SECONDS + 1)
        == frozenset()
    )


def test_refusal_memo_survives_a_corrupt_state_file(tmp_path: Path) -> None:
    module = _load()

    (tmp_path / module.REFUSAL_FILE).write_text("not json", encoding="utf-8")

    assert module.refused_folders(tmp_path, 63, now=1_000.0) == frozenset()
    module.record_refusal(tmp_path, 63, "deployment", now=1_000.0)
    assert module.refused_folders(tmp_path, 63, now=1_000.0) == frozenset({"deployment"})


def _git_binary() -> str:
    import shutil

    resolved = shutil.which("git")
    assert resolved is not None, "git is required for these tests"
    return resolved


def _init_repo(path: Path) -> None:
    import subprocess

    def run(*args: str) -> None:
        subprocess.run(  # noqa: S603 - fixed git commands on a temporary repo
            [_git_binary(), *args],
            cwd=path,
            check=True,
            capture_output=True,
            text=True,
        )

    path.mkdir(parents=True, exist_ok=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "T")
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    run("add", "seed.txt")
    run("commit", "-qm", "seed")


def test_sync_absorbs_main_when_the_branch_is_ahead_and_behind(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    module = _load()
    repo = tmp_path / "repo"
    _init_repo(repo)

    def run(*args: str) -> str:
        return subprocess.run(  # noqa: S603 - fixed git commands on a temporary repo
            [_git_binary(), *args], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()

    run("checkout", "-qb", "roadmap-implementation/campaign")
    (repo / "campaign.txt").write_text("batch\n", encoding="utf-8")
    run("add", "campaign.txt")
    run("commit", "-qm", "campaign batch")
    run("checkout", "-q", "main")
    (repo / "other.txt").write_text("other\n", encoding="utf-8")
    run("add", "other.txt")
    run("commit", "-qm", "other work")
    run("checkout", "-q", "roadmap-implementation/campaign")

    registered: list[str] = []
    monkeypatch.setattr(
        module, "_register_committed_work", lambda _root, base: registered.append(base)
    )

    # Ahead and behind at once used to hold every later run forever.
    assert module._campaign_relation(ahead=1, behind=1) == "diverged"
    before = run("rev-parse", "HEAD")
    assert module._sync_campaign_base(repo) == "current"
    assert run("rev-list", "--count", "HEAD..main") == "0"
    assert run("status", "--porcelain") == ""
    # `git merge` skips the post-commit hook, so the sync merge has to be enqueued by hand.
    # Without this the branch tip is never validated and a validated batch can never land.
    assert registered == [before]


def test_sync_leaves_no_half_merged_worktree_on_conflict(tmp_path: Path) -> None:
    import subprocess

    module = _load()
    repo = tmp_path / "repo"
    _init_repo(repo)

    def run(*args: str) -> str:
        return subprocess.run(  # noqa: S603 - fixed git commands on a temporary repo
            [_git_binary(), *args], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()

    run("checkout", "-qb", "roadmap-implementation/campaign")
    (repo / "shared.txt").write_text("campaign\n", encoding="utf-8")
    run("add", "shared.txt")
    run("commit", "-qm", "campaign edit")
    run("checkout", "-q", "main")
    (repo / "shared.txt").write_text("main\n", encoding="utf-8")
    run("add", "shared.txt")
    run("commit", "-qm", "main edit")
    run("checkout", "-q", "roadmap-implementation/campaign")

    assert module._sync_campaign_base(repo) == "sync-failed"
    # A half-merged tree would make the next run refuse with "campaign worktree is dirty".
    assert run("status", "--porcelain") == ""


def test_failed_batch_still_registers_its_commits(tmp_path: Path, monkeypatch) -> None:
    module = _load()
    repo = tmp_path / "repo"
    _init_repo(repo)

    calls: list[list[str]] = []

    def fake_run(arguments, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(arguments))

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "_git", lambda *a, **k: "newhead")

    module._register_committed_work(repo, "oldbase")

    assert ["ensure-range", "oldbase..HEAD"] == calls[0][-2:]
    assert calls[1][-1] == "wake"


def test_unchanged_head_registers_nothing(tmp_path: Path, monkeypatch) -> None:
    module = _load()
    calls: list[list[str]] = []
    monkeypatch.setattr(
        module.subprocess, "run", lambda arguments, **k: calls.append(list(arguments))
    )
    monkeypatch.setattr(module, "_git", lambda *a, **k: "same")

    module._register_committed_work(tmp_path, "same")

    assert calls == []


def test_unreceipted_campaign_head_is_registered_before_holding(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load()
    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.setattr(module.watchdog, "_active_session_leases", lambda *a, **k: [])
    monkeypatch.setattr(module.watchdog, "_recent_copilot_activity", lambda *a, **k: [])
    monkeypatch.setattr(module.watchdog, "_active_session_count", lambda *a, **k: 0)
    synced: list[Path] = []
    landed: list[Path] = []
    monkeypatch.setattr(module, "_sync_campaign_base", lambda root: synced.append(root))
    monkeypatch.setattr(module, "_land_validated_batch", lambda root: landed.append(root))
    monkeypatch.setattr(module, "_validation_receipt_exists", lambda *_a, **_k: False)

    def fake_git(*args: str, **_kwargs: object) -> str:
        return {
            "status": "",
            "branch": "roadmap-implementation/campaign",
            "rev-list": "3",
            "rev-parse": ".",
        }[args[0]]

    monkeypatch.setattr(module, "_git", fake_git)
    registered: list[str] = []
    monkeypatch.setattr(
        module,
        "_register_committed_work",
        lambda _root, base: registered.append(base),
    )

    result = module.run_cycle(repo, idle_seconds=1, timeout=1)

    assert result == "held: previous campaign head is awaiting central validation"
    # `git merge` skips the post-commit hook, so a merge commit made while absorbing main
    # is never enqueued. Waiting for a receipt the queue was never asked to produce holds
    # every later run forever.
    assert registered == ["main"]
    # Absorbing main first mints a new merge commit on every held run, so the head would
    # outrun validation for as long as any other session keeps committing.
    assert synced == []
    # Landing must still run. It only merges commits that already hold a receipt, so an
    # unvalidated tip says nothing about the validated work beneath it. Holding it back
    # here deadlocked the lane: the hold returned early and finished work never reached
    # main however long it waited.
    assert landed == [repo]


def test_landing_requires_a_receipt_and_leaves_live_edits_alone(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load()
    calls: list[list[str]] = []
    state = {"status": "", "incoming": "docs/roadmap/architecture/owned.md\n", "staged": ""}
    # Newest first, exactly as `git rev-list main..HEAD` reports it.
    ahead = ["freshest", "validated", "older"]
    receipted: set[str] = set()

    def fake_git(*args: str, **_kwargs: object) -> str:
        if args[0] == "diff":
            return state["staged"] if "--cached" in args else state["incoming"]
        if args[0] == "rev-list":
            return str(len(ahead)) if "--count" in args else "\n".join(ahead)
        return {"status": state["status"], "rev-parse": "campaignhead"}[args[0]]

    class _Result:
        returncode = 0

    monkeypatch.setattr(module, "_git", fake_git)
    monkeypatch.setattr(module, "_main_checkout", lambda _root: tmp_path)
    monkeypatch.setattr(module, "_register_committed_work", lambda *_a: None)
    monkeypatch.setattr(
        module, "_validation_receipt_exists", lambda _root, revision: revision in receipted
    )
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda arguments, **_k: calls.append(list(arguments)) or _Result(),
    )

    assert module._land_validated_batch(tmp_path) is None
    assert calls == []

    receipted.add("validated")
    state["status"] = " M docs/roadmap/architecture/owned.md"
    assert module._land_validated_batch(tmp_path) is None
    # The merge would rewrite a file another session is editing; that work must not be touched.
    assert calls == []

    state["status"] = " M docs/roadmap/architecture/elsewhere.md\n?? scratch.py"
    state["staged"] = "docs/roadmap/deployment/unrelated.md\n"
    assert module._land_validated_batch(tmp_path) is None
    # `git merge` refuses outright when the index differs from HEAD, even for paths the
    # merge would leave byte-identical. Attempting it anyway just fails and logs nothing.
    assert calls == []

    state["staged"] = ""
    assert module._land_validated_batch(tmp_path) == "landed validated on main"
    # Two refusals dressed as safety are gone. A dirty checkout is the normal state of the
    # primary worktree, so landing only needs the incoming paths to miss the live edits. And
    # the branch tip is the freshest commit and the least likely to hold a receipt, so
    # landing takes the newest ancestor that has one instead of racing its own production.
    assert calls[0] == ["git", "merge", "--no-ff", "--no-edit", "validated"]


def test_a_renamed_path_counts_as_a_live_edit_on_both_sides(tmp_path: Path, monkeypatch) -> None:
    module = _load()
    (tmp_path / "renamed.txt").write_text("", encoding="utf-8")

    monkeypatch.setattr(
        module,
        "_git",
        lambda *args, **_k: 'R  "old name.txt" -> renamed.txt' if args[0] == "status" else "",
    )
    # Porcelain reports a rename as one line naming two paths; a merge that rewrites either
    # side disturbs the same in-flight change, so both have to be treated as held.
    assert module._dirty_paths(tmp_path) == {"old name.txt", "renamed.txt"}
